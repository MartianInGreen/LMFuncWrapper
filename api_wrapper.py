import os
import json
import uuid
import re
from openai import OpenAI
from dicttoxml import dicttoxml
import xmltodict

def auth(headers):
    """
    Authenticate the request based on the API key.

    Args:
        headers (dict): The headers of the request.

    Returns:
        bool: True if the request is authorized, False otherwise.
    """
    if headers["x-api-key"] != os.getenv("SERVICE_API_KEY"):
        raise Exception("Unauthorized")
    else:
        return True

def load_params(event):
    """
    Load the parameters from the event.

    Args:
        event (dict): The event payload.

    Returns:
        dict: The parsed parameters.
    """
    try:
        body = json.loads(event["body"])
        headers = event["headers"]
        auth(headers)
        return body
    except Exception as e:
        raise Exception("Error loading parameters: " + str(e))

def add_system_message(messages, functions):
    """
    Add a system message to the list of messages.

    Args:
        messages (list): The list of messages.
        functions (str): The string representation of the available functions.

    Returns:
        list: The updated list of messages.
    """
    with open("instructionsV2.md", "r") as file:
        content = file.read().replace("{{tools}}", str(functions))

    if messages[-1]["role"] == "tool":
        messages.insert(-1, {"role": "system", "content": content})
    else:
        messages.append({"role": "system", "content": content})

    for message in messages:
        if message["role"] == "tool":
            message["role"] = "user"
            message["content"] = "*SYSTEM MESSAGE*\nResponse from the tool you just called.\n<tool_response source=" + message["name"] + ">\n" + message["content"] + "\n</tool_response>"

    return messages

def parse_tool_json(raw_json):
    """
    Parse the tool call JSON.

    Args:
        raw_json (dict): The raw JSON data.

    Returns:
        list: The parsed tool calls.
    """
    tool_name = raw_json["tool_call"]["tool_name"]["#text"]
    args = {}

    for arg_name, arg_value in raw_json["tool_call"]["parameters"].items():
        if isinstance(arg_value, dict):
            args[arg_name] = arg_value.get("#text", arg_value)
        elif arg_name != "@type":
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
    """
    Build the return JSON data.

    Args:
        message (dict): The message to be included in the response.
        tool_calls (list): The list of tool calls.
        id (str): The unique identifier of the response.
        created (int): The timestamp of the response creation.
        model (str): The name of the model used.
        stream (bool): Whether the response was streamed or not.
        finish_reason (str): The reason for the response termination.

    Returns:
        dict: The return JSON data.
    """
    object = "chat.completion"

    if tool_calls is None:
        messages = [{
            'message': {
                'role': message["role"],
                'content': message["content"]
            }
        }]
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
    """
    The main entry point for the Lambda function.

    Args:
        event (dict): The event payload.
        context (dict): The context of the Lambda function.

    Returns:
        dict: The response JSON data.
    """
    body = load_params(event)

    try: 
        model = body["model"]
        messages = body["messages"]
        functions = body.get("tools", "No tools available. Do not call any!")
        streaming = body.get("stream", False)

        if streaming:
            return {
                "statusCode": 401,
                "body": "Streaming is not supported in this version of the API. Please set 'stream' to 'false'."
            }

        messages = add_system_message(messages, functions)

    except Exception as e:
        raise Exception("Error loading parameters: " + str(e))

    try: 
        client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=os.getenv("OPENROUTER_API_KEY"),
        )

        completion = client.chat.completions.create(
            model=model,
            messages=messages,
            stream=streaming,
        )

        tool_call_json = None

        if streaming:
            tool_call_xml = ""
            start_tool_call = False
            tool_call_json = None
            message = None
            finish_reason = None
            for chunk in completion: 
                if chunk.choices[0].finish_reason is not None: 
                    finish_reason = chunk.choices[0].finish_reason
                if "<tool" in chunk.choices[0].delta.content and not start_tool_call:
                    tool_call_xml += chunk.choices[0].delta.content
                    start_tool_call = True
                elif start_tool_call:
                    tool_call_xml += chunk.choices[0].delta.content
                    if "</tool_call>" in tool_call_xml:
                        start_tool_call = False
                        tool_call_json = xmltodict.parse(tool_call_xml)
                elif tool_call_json is None:
                    if message is None:
                        message = ""
                    message += chunk.choices[0].delta.content

            if tool_call_json is not None:
                parsed_json = parse_tool_json(tool_call_json)
            else:
                parsed_json = None

            message = {
                "role": "assistant",
                "content": message
            }

            json_return = build_return_json(message, parsed_json, chunk.id, chunk.created, model, streaming, finish_reason)
            return json_return

        if not streaming:
            message = {
                "role": "assistant",
                "content": re.sub(r'(<tool_call>)[\s\S]*(<\/tool_call>)[\s\S]*', '', completion.choices[0].message.content)
            }

            message["content"] = message["content"].replace("<message>\n", "").replace("<message>", "")
            message["content"] = message["content"].replace("\n</message>", "").replace("</message>", "")
            #message["content"] = message["content"].replace("<thought>\n", "*").replace("<thought>", "*")
            #message["content"] = message["content"].replace("\n</thought>", "*").replace("</thought>", "*")

            tool_call_xml = re.search(r'(<tool_call>)[\s\S]*(<\/tool_call>)', completion.choices[0].message.content)
            if tool_call_xml is not None:
                tool_call_xml = tool_call_xml.group()
                tool_call_json = xmltodict.parse(tool_call_xml)
                parsed_json = parse_tool_json(tool_call_json)
            else:
                parsed_json = None

            json_return = build_return_json(message, parsed_json, completion.id, completion.created, model, streaming)
            return json_return

    except Exception as e:
        raise Exception("Error calling API: " + str(e))