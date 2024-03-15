from openai import OpenAI
import os, json, re, uuid

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
    with open("api_wrapper.md", "r") as file:
        content = file.read()
        content = content.replace("{{tools}}", str(functions))

    # Insert
    messages.append({"role": "system", "content": content})
    #print(messages)
    return messages

def lambda_handler(event, context):
    body = load_params(event)
    print(body)

    try: 
        model = body["model"]
        messages = body["messages"]
        try: 
            functions = body["tools"]
            print(functions)
        except:
            functions = "No tools available."
            print(functions)
        try:
            streaming = body["stream"]
        except:
            streaming = False

        # Add system message
        messages = add_system_message(messages, functions)

        # Modify tool response messages
        for message in messages:
            if message["role"] == "tool":
                message["role"] = "system"
                message["content"] = "Tool response:\n\n" + message["content"]
    except Exception as e:
        raise Exception("Error loading parameters: " + str(e))
    
    try: 
        client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=os.getenv("OPENROUTER_API_KEY"),
        )

        completion = client.chat.completions.create(
            model=model,
            messages=messages
        )
    except Exception as e:
        raise Exception("Error calling API: " + str(e))

    # Determine action type
    try: 
        print(completion)
        raw_response = completion.choices[0].message.content
        converted_json_string = False
        #print(response)
        try:
            json_string = re.search('```json\n(.*?)\n```', raw_response , re.DOTALL).group(1)
        except:
            try:
                # Search for JSON string without code block -> Message starts with {
                no_nl = raw_response.replace('{\n', '{').replace('\n}', '}')
                no_nl = no_nl.replace('}\n', '}').replace('\n{', '{')

                if no_nl.startswith('[['):
                    # Remove leading [[some_text]]
                    print("Removing leading [[some_text]]")
                    no_nl = re.sub(r'^\[\[.*?\]\]', '', no_nl)
                if not no_nl.startswith('{'):
                    print("Removing leading text")
                    # Match any leading text before the JSON string
                    no_nl = re.sub(r'^[^{]*' '', no_nl)

                match = re.search(r'^\s*?({.*})', no_nl, re.DOTALL)
                if match:
                    json_string = match.group(1)
                    response = json.loads(json_string)
                    converted_json_string = True
                    print("Converted JSON string in first alternative step.")
                else:
                    print("Error parsing response: No JSON string found in first alternative step.")
                    raise Exception("Error parsing response: No JSON string found")
            except:
                # Sometimes raw response looks smth. like this: pondera({"query": "latest news about OpenAI", "type": "deep", "focus": "web", "country": "US", "freshness": "week"})
                match = re.search(r'(\w+)\((.*?)\)', raw_response, re.DOTALL)

                if match:
                    function_name = match.group(1)
                    function_args = match.group(2)

                    json_string = '{"action": "tool_call", "action_data": {"name": "' + function_name + '", "arguments": ' + function_args + '}}'
                try:
                    response = json.loads(json_string)
                    converted_json_string = True
                except:
                    pass 

                if not converted_json_string:
                    json_string = '{"action": "text_message", "action_data": {"message": ' + json.dumps(raw_response) + '}}'
        
        if not converted_json_string:
            try:
                # Remove any leading or trailing characters before { and after the last } (including normal text)
                json_string = re.sub(r'^.*?({.*}).*$', r'\1', json_string, flags=re.DOTALL)

                response = json.loads(json_string)
            except Exception as e:
                print("Response:")
                print(raw_response)
                print("JSON string:")
                print(json_string)
                raise Exception("Error parsing response: " + str(e))

        print(json_string)

        try: 
            action = response["action"]
            # See if action is string
            if isinstance(action, str):
                action = action.lower()
            else:
                action = str(action["type"]).lower()
        except:
            raise Exception("Error parsing response: No action found")
        
        # Check if action is valid
        if action not in ["text_message", "tool_call"]:
            raise Exception("Error parsing response: Invalid action")
        
        # Get action data
        try:
            action_data = response["action_data"]
        except:
            try:
                alt_action_data = response["action"]["action_data"]
            except:
                raise Exception("Error parsing response: No action data found")

        if action == "text_message": 
            try: 
                response_message = action_data["message"]
            except:
                try: 
                    response_message = alt_action_data["message"]
                except:
                    raise Exception("Error parsing response: No message found")
        if action == "tool_call":        
            try: 
                tool_name = action_data["name"]
                tool_args = action_data["arguments"]
            except:
                try: 
                    tool_name = alt_action_data["name"]
                    tool_args = alt_action_data["arguments"]
                except:
                    try:
                        tool_name = response["action"]["name"]
                        tool_args = response["action"]["arguments"]
                    except:
                        raise Exception("Error parsing response: No tool data found")


        # If action is a message, return it
        if action == "text_message":
            completion.choices[0].message.content = response_message
            
            return_data = {
                'id': completion.id,
                'object': completion.object,
                'created': completion.created,
                'model': completion.model,
                'usage': {
                    # CompletionUsage(completion_tokens=68, prompt_tokens=500, total_tokens=568, total_cost=0.00252)
                    'completion_tokens': completion.usage.completion_tokens,
                    'prompt_tokens': completion.usage.prompt_tokens,
                    'total_tokens': completion.usage.total_tokens,
                    'total_cost': completion.usage.total_cost    
                },
                'choices': [{
                    'message': {
                        'role': completion.choices[0].message.role,
                        'content': completion.choices[0].message.content
                    },
                    'finish_reason': 'stop',
                }]
            }

            if streaming == True:
                return_data = {
                    "choices": [{
                        "index": 0,
                        "delta": {
                            "role": completion.choices[0].message.role,
                            "content": completion.choices[0].message.content
                        },
                        "finish_reason": "stop"
                    }],
                    "id": completion.id,
                    "object": completion.object,
                    "created": completion.created,
                    "model": completion.model,
                }

                print("data: " + json.dumps(return_data))
                return json.dumps(return_data)

            print(json.dumps(return_data))

            return return_data
        elif action == "tool_call":
            completion.choices[0].message.content = None

            return_data = {
                'id': completion.id,
                'object': completion.object,
                'created': completion.created,
                'model': completion.model,
                'usage': {
                    # CompletionUsage(completion_tokens=68, prompt_tokens=500, total_tokens=568, total_cost=0.00252)
                    'completion_tokens': completion.usage.completion_tokens,
                    'prompt_tokens': completion.usage.prompt_tokens,
                    'total_tokens': completion.usage.total_tokens,
                    'total_cost': completion.usage.total_cost    
                },
                'choices': [{
                    'message': {
                        'role': completion.choices[0].message.role,
                        'content': completion.choices[0].message.content,
                        'tool_calls': [{
                            'id': str(uuid.uuid4()),
                            'function': {
                                'arguments': json.dumps(tool_args),
                                'name': tool_name,
                            },
                            'type': 'function'
                        }]
                    },
                    'finish_reason': completion.choices[0].finish_reason,
                }]
            }

            if streaming:
                return_data = {
                    "choices": [{
                        "index": 0,
                        "delta": {
                            "role": completion.choices[0].message.role,
                            "content": completion.choices[0].message.content,
                            "tool_calls": [{
                                "id": str(uuid.uuid4()),
                                "function": {
                                    "arguments": json.dumps(tool_args),
                                    "name": tool_name,
                                },
                                "type": "function"
                            }]
                        },
                        "finish_reason": completion.choices[0].finish_reason
                    }],
                    "id": completion.id,
                    "object": completion.object,
                    "created": completion.created,
                    "model": completion.model,
                }

            print(return_data)
            return return_data
        
        print(response)
    except Exception as e:
        raise Exception("Error parsing response: " + str(e))