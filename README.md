# LMFuncWrapper
Allow more language models to function call via an JSON Agent API wrapper 

## Installation 

**Installation**

1. Create an AWS account (you can do this for free, you get a lot of AWS Lambda function calls completly free each month)
2. Create a lambda function
   1. Give it a name that is easily identifiable 
   2. Set the runtime to Python (preferably 3.10 or 3.11 both should work)
   3. Under advanced settings click Enable function URL 
   4. Set Auth type to None (We'll have own custom auth in most plugins, however be aware that this makes your functions publicly accessible in theory)
   5. Enable "Configure cross-origin resource sharing (CORS)"
3. Configure lambda function
   1. Go to configuration/General -> Set timeout according to each function (you can probably just set this to around 1-3m)
   2. Go to configuration/Function URL and click on edit
      1. Set allow Origin to * (or you can set it to the typingmind domain)
      2. Add x-api-key, access-control-allow-origin, and content-type to "Expose headers" and "Allow headers"
      3. Under Allow methods add *
      4. Enable Allow credentials
   3. Go to configuration/Environment variables -> Set your API Keys and set the "SERVICE_API_KEY" to what you want your API key to be
   4. Go to configuration/Environment variables -> Set your "OPENROUTER_API_KEY"
4. Copy the python code to your functions lambda_function.py & copy the api_wrapper.md file next to your python function
5. Install dependencies on AWS Lambda function
   1. Open a Linux Terminal (Under WSL or native)
   2. Create a folder `mkdir python`
   3. Run `python3 -m pip install openai --target ./`
   4. Zip the folder `cd .. && zip -r my-lambda-layer.zip python`
   5. Create a new Layer on AWS, select the python version and upload your ZIP file
   6. Add layer to your function
6. Copy your function URL 
7. Add a new model to typingmind
   1. Use Model-ID's from Openrouter and set context length
   2. Set endpoint to function url
   3. Add custom header {"x-api-key": "same as your SERVICE_API_KEY"}
   4. Enable function calling (and optionally Vision if the base model supports that.)
