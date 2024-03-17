from openai import OpenAI
from dicttoxml import dicttoxml
import xmltodict
import os, json, uuid, re
#from rich import print

def auth(headers):
    if headers["x-api-key"] != os.getenv("SERVICE_API_KEY"):
        raise Exception("Unauthorized")
    else:
        return True
    
def load_params(event): 
    try:
        body = json.loads(event["body"])
        headers = event["headers"]
        auth(headers)
        return body
    except Exception as e:
        raise Exception("Error loading parameters: " + str(e))
    
def add_system_message(messages, functions):
     # Read api_wrapper.md
    with open("instructionsV2.md", "r") as file:
        content = file.read()
        content = content.replace("{{tools}}", str(functions))

    # Insert system message
    # if last message was a tool response, insert system message before it
    if messages[-1]["role"] == "tool":
        messages.insert(-1, {"role": "system", "content": content})
    else:
        messages.append({"role": "system", "content": content})
    #print(messages)

    # Replace tool response with system message
    for message in messages:
        if message["role"] == "tool":
            message["role"] = "user"
            message["content"] = "*SYSTEM MESSAGE*\nResponse from the tool you just called.\n<tool_response source=" + message["name"] + ">\n" + message["content"] + "\n</tool_response>"

    return messages

def parse_tool_json(raw_json):
    tool_name = raw_json["tool_call"]["tool_name"]["#text"]
    args = {}

    for arg_name, arg_value in raw_json["tool_call"]["parameters"].items():
        if isinstance(arg_value, dict):
            if '#text' in arg_value:
                args[arg_name] = arg_value['#text']
            else:
                args[arg_name] = arg_value
        else:
            if arg_name != "@type":
                args[arg_name] = arg_value

    tool_calls = [{
        'id': str(uuid.uuid4()),
        'function': {
            'name': tool_name,
            'arguments': json.dumps(args)
        },
        'type': 'function'
    }]
    
    return tool_calls

def build_return_json(message, tool_calls, id, created, model, stream, finish_reason=None):
    if False:
        object = "chat.completion"

        # Normal messages
        if tool_calls == None:
            messages = [{
                'index': 0,
                'delta': {
                    'role': message["role"],
                    'content': message["content"]
                    },
                'finish_reason': finish_reason
            }]
        if tool_calls != None:
            messages = [{
                'index': 0,
                'delta': {
                    'role': message["role"],
                    'content': message["content"],
                    'tool_calls': tool_calls
                },
                'finish_reason': finish_reason
            }]

    else:
        object = "chat.completion"

        # Normal messages
        if tool_calls == None:
            messages = [{
                'message': {
                    'role': message["role"],
                    'content': message["content"]
                },
            }]
        # Tool messages
        else:
            messages = [{
                'message': {
                    'role': message["role"],
                    'content': message["content"],
                    'tool_calls': tool_calls
                }
            }]
    

    return_data = {
        'choices': messages,
        'id': id,
        'object': object,
        'created': created,
        'model': model,
    }

    return return_data
    
def lambda_handler(event, context):
    body = load_params(event)
    print(body)

    try: 
        model = body["model"]
        messages = body["messages"]
        try: 
            functions = body["tools"]
            functions = dicttoxml(functions, custom_root="tools", xml_declaration=False)
        except:
            functions = "No tools available. Do not call any!"
        try:
            streaming = body["stream"]
        except:
            streaming = False

        # Add system message
        messages = add_system_message(messages, functions)

        print(messages)

    except Exception as e:
        raise Exception("Error loading parameters: " + str(e))
    
    # Call OpenRouter API

    try: 
        client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=os.getenv("OPENROUTER_API_KEY"),
        )

        completion = client.chat.completions.create(
            model=model,
            messages=messages,
            stream=streaming,
            #stop=["</tool_call>"]
        )

        print(completion)
        tool_call_json = None

        if streaming == True: 
            tool_call_xml = ""
            start_tool_call = False
            tool_call_json = None
            message = None
            finish_reason = None
            for chunk in completion: 
                #print(chunk)
                if chunk.choices[0].finish_reason is not None: 
                    print("\nSTOP")
                    finish_reason = chunk.choices[0].finish_reason
                if "<tool" in chunk.choices[0].delta.content and start_tool_call == False:
                    tool_call_xml = tool_call_xml + chunk.choices[0].delta.content
                    start_tool_call = True
                elif start_tool_call == True:
                    tool_call_xml = tool_call_xml + chunk.choices[0].delta.content
                    if "</tool_call>" in tool_call_xml:
                        start_tool_call = False
                        tool_call_json = xmltodict.parse(tool_call_xml)
                elif tool_call_json == None:
                    if message == None:
                        message = ""
                    message = message + chunk.choices[0].delta.content
                    #print(build_return_json(chunk.choices[0].delta, tool_call_json, chunk.id, chunk.created, model, streaming, finish_reason))
            
            if tool_call_json != None:
                print("Found tool call!")
                parsed_json = parse_tool_json(tool_call_json)
            else:
                parsed_json = None

            message = {
                "role": "assistant",
                "content": message
            }

            json_return = build_return_json(message, parsed_json, chunk.id, chunk.created, model, streaming, finish_reason)
            return json_return

        if streaming == False:
            message = {
                "role": "assistant",
                "content": re.sub(r'(<tool_call>)[\s\S]*(<\/tool_call>)[\s\S]*', '', completion.choices[0].message.content)
            }


            message["content"] = message["content"].replace("<message>\n", "").replace("<message>", "")
            message["content"] = message["content"].replace("</message>\n", "").replace("</message>", "")

            message["content"] = message["content"].replace("<thought>\n", "*").replace("<thought>", "*")
            message["content"] = message["content"].replace("</thought>\n", "*").replace("</thought>", "*")

            # Find tool calls using regex
            tool_call_xml = re.search(r'(<tool_call>)[\s\S]*(<\/tool_call>)', completion.choices[0].message.content)
            if tool_call_xml != None:
                tool_call_xml = tool_call_xml.group()
                tool_call_json = xmltodict.parse(tool_call_xml)
                parsed_json = parse_tool_json(tool_call_json)
            else:
                parsed_json = None

            json_return = build_return_json(message, parsed_json, completion.id, completion.created, model, streaming)
            return json_return
    except Exception as e:
        raise Exception("Error calling API: " + str(e))