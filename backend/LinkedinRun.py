from typing_extensions import TypedDict,Annotated,Literal
from dotenv import load_dotenv
from langgraph.graph import StateGraph,END,START
from langchain_core.messages import BaseMessage,HumanMessage,AIMessage,ToolMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph.message import add_messages
from langgraph.checkpoint.memory import MemorySaver,InMemorySaver
from pydantic import BaseModel,Field
from langchain.tools import tool, InjectedToolCallId
from langsmith import traceable
import os 
import re
from langgraph.types import interrupt,Command
import operator
import time
import uuid
import json
from langgraph.prebuilt import ToolNode,tools_condition
from fastapi import FastAPI,HTTPException,Query
import requests
from fastapi.responses import JSONResponse, RedirectResponse, HTMLResponse
import jwt
import uvicorn
import threading
import webbrowser
from linkedinPrompts import prompts
load_dotenv()
GOOGLE_API_KEY=os.getenv('GOOGLE_API_KEY')
# create a linkedin post on developing concern for software developer with the inhancement andinnovation in the field of agentic coding

langsmith_api_key = os.getenv("LANGSMITH_API_KEY", "").strip()
if langsmith_api_key:
    os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
    os.environ.setdefault("LANGCHAIN_PROJECT", "LangGraph-Linkedin")
    os.environ.setdefault("LANGCHAIN_CALLBACKS_BACKGROUND", "true")
    print(" LangSmith Observability: ON")
    print(f"   Project: {os.environ.get('LANGCHAIN_PROJECT')}")
    print(f"   Tracing: {os.environ.get('LANGCHAIN_TRACING_V2')}")
else:
    os.environ["LANGCHAIN_TRACING_V2"] = "false"
    print(" LangSmith Observability: OFF (no LANGSMITH_API_KEY)")


llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash", 
    temperature=0.7,
    google_api_key=GOOGLE_API_KEY 
)

from fastapi.middleware.cors import CORSMiddleware

app=FastAPI()

frontend_url = os.getenv("FRONTEND_URL", "")
cors_origins = ["http://localhost:5173", "http://localhost:3000"]
if frontend_url:
    cors_origins.extend([url.strip() for url in frontend_url.split(",") if url.strip()])

# Allow CORS for configured frontend URLs + local development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

CLIENT_ID = os.getenv('CLIENT_ID')
CLIENT_SECRET = os.getenv('CLIENT_SECRET')
REDIRECT_URI = os.getenv('REDIRECT_URI')
TOKEN_FILE = "linkedin_tokens.json"
pending_auth = {}

def save_tokens(tokens):
    with open(TOKEN_FILE, "w") as f:
        json.dump(tokens, f)

def load_tokens():
    if os.path.exists(TOKEN_FILE):
        try:
            with open(TOKEN_FILE, "r") as f:
                return json.load(f)
        except:
            return None
    return None

class PostState(TypedDict, total=False):
    messages: list[BaseMessage]
    response: str
    feedback: str
    access_token: str
    person_id: str

@tool
def LinkedinPost_tool(topic: str, tool_call_id: Annotated[str, InjectedToolCallId]):
    """Create a professional LinkedIn post and ask for approval."""

    prompt = f"Create a single short professional LinkedIn post on:{topic} \n {prompts} \n Now create the post on: {topic}"
    response = llm.invoke(prompt).content

    # HITL -
    approval_result = interrupt({
        "type": "post_approval",
        "question": "Do you approve this post? (yes/no)",
        "post": response
    })

    if isinstance(approval_result, dict):
        approved = approval_result.get("answer", "").strip().lower()
        response = approval_result.get("post", response)  # Use preserved post
        feedback = approval_result.get("feedback", "")
    else:
        approved = str(approval_result).strip().lower()
        # If the answer is not yes/no, maybe it's direct feedback string
        feedback = approved if approved not in ["yes", "no"] else ""

    if approved == "yes":
        return Command(
            goto="ensure_auth",
            update={
                "messages": [
                    ToolMessage(content=f"Approved Post:\n{response}", tool_call_id=tool_call_id)
                ],
                "response": response 
            }
        )

    # Rejection handling (either explicit 'no' or direct feedback string)
    if not feedback:
        feedback_result = interrupt({
            "type": "feedback",
            "question": "Please provide feedback to improve the post."
        })
        
        if isinstance(feedback_result, dict):
            feedback = feedback_result.get("feedback", "")
        else:
            feedback = str(feedback_result)

    return Command(
        goto="agent",
        update={
            "messages": [
                ToolMessage(content=f"Post rejected. User feedback: {feedback}", tool_call_id=tool_call_id),
                HumanMessage(content=f"""Create a new LinkedIn post on '{topic}' with this feedback: {feedback}
                Remember:
                - NO asterisks or bullet points
                - Sound human and conversational
                - Use blank lines between paragraphs
                - Keep it 150-250 words
                - End with an engaging question
                - 3-4 hashtags at the end""" 
                )
            ]
        }
    )


tools=[LinkedinPost_tool]
llm_with_tools=llm.bind_tools(tools)

@traceable(name='Agent_fun')
def agent(state: PostState):

    response = llm_with_tools.invoke(state["messages"])

    return {
        "messages": state["messages"] + [response]
    }


tool_node=ToolNode(tools)


@traceable(name='EnsureLinkedInAuth_node')
def ensure_linkedin_auth(state: PostState):

    # 1. Check if already in state
    if state.get("access_token"):
        return state

    # 2. Check if stored in local file (Persistence)
    stored = load_tokens()
    if stored and stored.get("access_token"):
        print(" Using stored LinkedIn tokens")
        return {
            "access_token": stored.get("access_token"),
            "person_id": stored.get("person_id")
        }

    if not state.get("access_token"):
        # Generate unique state for OAuth (will be used to link back to thread)
        oauth_state = str(uuid.uuid4())
        
        auth_url = (
            "https://www.linkedin.com/oauth/v2/authorization"
            f"?response_type=code"
            f"&client_id={CLIENT_ID}"
            f"&redirect_uri={REDIRECT_URI}"
            f"&scope=openid%20profile%20w_member_social"
            f"&state={oauth_state}"
        )

        # Interrupt and wait for token to be provided after OAuth
        token_data = interrupt({
            "type": "linkedin_auth_required",
            "message": "Please authenticate with LinkedIn",
            "url": auth_url,
            "oauth_state": oauth_state
        })
        
        # After resume, token_data should contain access_token and person_id
        if isinstance(token_data, dict):
            return {
                "access_token": token_data.get("access_token"),
                "person_id": token_data.get("person_id")
            }

    return state


@traceable(name='PublishToLinkedIn_node')
def publish_to_linkedin(state: PostState):
    """Publish the approved post to LinkedIn"""
    
    access_token = state.get("access_token")
    person_id = state.get("person_id")
    post_text = state.get("response")
    
    if not all([access_token, person_id, post_text]):
        return {"messages": state.get("messages", []) + [AIMessage(content="Missing required data for posting")]}
    
    url = "https://api.linkedin.com/v2/ugcPosts"

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0"
    }

    body = {
        "author": f"urn:li:person:{person_id}",
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {
                    "text": post_text
                },
                "shareMediaCategory": "NONE"
            }
        },
        "visibility": {
            "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
        }
    }

    response = requests.post(url, headers=headers, json=body)
    result = response.json()
    
    if response.status_code == 201:
        return {"messages": state.get("messages", []) + [AIMessage(content=f"✅ Post published successfully to LinkedIn!")]}
    else:
        return {"messages": state.get("messages", []) + [AIMessage(content=f"❌ Failed to post: {result}")]}




@app.get("/callback")
def callback(code: str, state: str = Query(...)):
    """LinkedIn OAuth callback - exchanges code for token"""
    
    url = "https://www.linkedin.com/oauth/v2/accessToken"

    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    }

    response = requests.post(url, data=data)
    token_data = response.json()

    if "error" in token_data:
        return {"error": token_data}

    access_token = token_data.get("access_token")
    
    # Decode ID token to get person_id
    decoded = jwt.decode(token_data["id_token"], options={"verify_signature": False})
    person_id = decoded["sub"]

    # Store tokens with oauth_state as key
    token_obj = {
        "access_token": access_token,
        "person_id": person_id
    }
    pending_auth[state] = token_obj
    
    # Also save to local file for persistence across sessions
    save_tokens(token_obj)

    # HTML response for a beautiful popup window that auto-closes
    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Authorization Successful</title>
        <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@500;600;700&family=Inter:wght@400;500&display=swap" rel="stylesheet">
        <style>
            body {{
                margin: 0;
                height: 100vh;
                display: flex;
                align-items: center;
                justify-content: center;
                background-color: #060608;
                font-family: 'Inter', sans-serif;
                color: #f4f4f5;
                overflow: hidden;
            }}
            .container {{
                text-align: center;
                background: rgba(20, 20, 28, 0.70);
                backdrop-filter: blur(20px);
                border: 1px solid rgba(255,255,255,0.07);
                border-radius: 24px;
                padding: 3rem 2rem;
                max-width: 400px;
                box-shadow: 0 8px 40px rgba(0,0,0,0.55);
                animation: fadeUp 0.5s cubic-bezier(0.16, 1, 0.3, 1) forwards;
                opacity: 0;
                transform: translateY(20px);
            }}
            .icon-wrapper {{
                width: 80px;
                height: 80px;
                background: rgba(16, 185, 129, 0.1);
                border: 1px solid rgba(16, 185, 129, 0.3);
                border-radius: 50%;
                display: flex;
                align-items: center;
                justify-content: center;
                margin: 0 auto 1.5rem;
                box-shadow: 0 0 40px rgba(16, 185, 129, 0.12);
            }}
            .icon-wrapper svg {{
                width: 40px;
                height: 40px;
                color: #34d399;
            }}
            h1 {{
                font-family: 'Outfit', sans-serif;
                margin: 0 0 0.5rem;
                font-size: 1.75rem;
                font-weight: 600;
            }}
            p {{
                color: #a1a1aa;
                margin: 0 0 2rem;
                font-size: 0.95rem;
                line-height: 1.5;
            }}
            .loader {{
                width: 24px;
                height: 24px;
                border: 2px solid rgba(255,255,255,0.1);
                border-top-color: #60a5fa;
                border-radius: 50%;
                animation: spin 1s linear infinite;
                margin: 0 auto;
            }}
            @keyframes fadeUp {{
                to {{ opacity: 1; transform: translateY(0); }}
            }}
            @keyframes spin {{
                to {{ transform: rotate(360deg); }}
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="icon-wrapper">
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path>
                    <polyline points="22 4 12 14.01 9 11.01"></polyline>
                </svg>
            </div>
            <h1>Authentication Successful!</h1>
            <p>You have successfully connected your LinkedIn account. You can now safely close this window to continue.</p>
            <div class="loader"></div>
        </div>

        <script>
            // Notify the parent window that authentication was successful
            if (window.opener && !window.opener.closed) {{
                window.opener.postMessage({{
                    type: 'LINKEDIN_AUTH_SUCCESS',
                    state: '{state}'
                }}, '*');
            }}
            
            // Auto-close after a short delay so the user sees the success message
            setTimeout(() => {{
                window.close();
            }}, 2000);
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content, status_code=200)


@app.post("/start")
def start_workflow(topic: str, thread_id: str = None):
    """Start a new LinkedIn post workflow"""
    
    if not thread_id:
        thread_id = str(uuid.uuid4())
    
    # Create descriptive run name for LangSmith
    short_topic = topic[:30].replace(" ", "_") if len(topic) > 30 else topic.replace(" ", "_")
    
    config = {
        "configurable": {"thread_id": thread_id},
        "run_name": f"API_Start_{short_topic}",
        "metadata": {"topic": topic, "mode": "API", "endpoint": "start"},
        "tags": ["linkedin", "api-mode", "start"]
    }
    
    input_data = {
        "messages": [
            HumanMessage(content=f"Create a short LinkedIn post on {topic}")
        ]
    }
    
    events = list(workflow.stream(input_data, config=config))
    last_event = events[-1] if events else {}
    
    # Extract the interrupt message (the generated post)
    if "__interrupt__" in last_event:
        interrupt_value = last_event["__interrupt__"][0].value
        return {
            "thread_id": thread_id,
            "status": "awaiting_approval",
            "generated_post": interrupt_value,
            "action_required": "Reply with 'yes' to approve or 'no' to provide feedback",
            "next_step": f"POST /resume?thread_id={thread_id}&reply=yes (or no)"
        }
    
    return {
        "thread_id": thread_id,
        "status": "completed",
        "events": str(last_event)
    }


@app.post("/resume")
def resume_workflow(thread_id: str, reply: str):
    """Resume workflow with user reply (yes/no/feedback/done)"""
    
    # Try to parse the reply as JSON in case it's a rich object
    try:
        reply_data = json.loads(reply)
        action_indicator = reply_data.get("answer", "") if isinstance(reply_data, dict) else str(reply_data)
    except:
        reply_data = reply
        action_indicator = str(reply)
    
    # Determine the action type for better naming
    action = "approve" if action_indicator.lower() == "yes" else "reject" if action_indicator.lower() == "no" else "auth" if action_indicator.lower() == "done" else "feedback"
    
    config = {
        "configurable": {"thread_id": thread_id},
        "run_name": f"API_Resume_{action}",
        "metadata": {"reply": reply, "mode": "API", "endpoint": "resume", "action": action},
        "tags": ["linkedin", "api-mode", "resume", action]
    }
    
    try:
        # Check if thread exists
        current_state = workflow.get_state(config)
        if not current_state or not current_state.values:
            return {
                "thread_id": thread_id,
                "status": "error",
                "error": "Thread not found. The server may have restarted or you're using an old thread_id.",
                "action": "Start a new workflow with POST /start?topic=<topic>"
            }
        
        # If reply is 'done' and we have pending auth, use the token data
        if reply.lower() == "done":
            # Check pending_auth for any matching oauth_state
            if current_state.tasks:
                for task in current_state.tasks:
                    if hasattr(task, 'interrupts') and task.interrupts:
                        for intr in task.interrupts:
                            if isinstance(intr.value, dict) and "oauth_state" in intr.value:
                                oauth_state = intr.value["oauth_state"]
                                if oauth_state in pending_auth:
                                    reply_data = pending_auth.pop(oauth_state)
                                    break
        
        input_data = Command(resume=reply_data)
        
        events = list(workflow.stream(input_data, config=config))
        last_event = events[-1] if events else {}
        
        # Check if there's an interrupt
        if "__interrupt__" in last_event:
            interrupt_value = last_event["__interrupt__"][0].value
            
            # Check if it's LinkedIn auth interrupt
            if isinstance(interrupt_value, dict) and interrupt_value.get("type") == "linkedin_auth_required":
                return {
                    "thread_id": thread_id,
                    "status": "awaiting_linkedin_auth",
                    "message": "🔐 LinkedIn Authentication Required",
                    "auth_url": interrupt_value["url"],
                    "oauth_state": interrupt_value["oauth_state"],
                    "action_required": "1. Open the auth_url in browser\n2. Authenticate with LinkedIn\n3. After callback, call POST /resume?thread_id={}&reply=done".format(thread_id)
                }
            
            # Feedback interrupt (when user said 'no')
            if interrupt_value == "Please provide feedback to improve the post.":
                return {
                    "thread_id": thread_id,
                    "status": "awaiting_feedback",
                    "message": interrupt_value,
                    "action_required": f"POST /resume?thread_id={thread_id}&reply=<your feedback>"
                }
            
            # New post generated after feedback
            return {
                "thread_id": thread_id,
                "status": "awaiting_approval",
                "generated_post": interrupt_value,
                "action_required": "Reply with 'yes' to approve or 'no' to provide feedback",
                "next_step": f"POST /resume?thread_id={thread_id}&reply=yes (or no)"
            }
        
        # Check if workflow completed (publish node output)
        if "publish" in last_event:
            messages = last_event["publish"].get("messages", [])
            if messages:
                last_message = messages[-1].content if hasattr(messages[-1], 'content') else str(messages[-1])
                return {
                    "thread_id": thread_id,
                    "status": "completed",
                    "result": last_message
                }
        
        # Check current state
        current_state = workflow.get_state(config)

        # If agent produced a draft directly (without interrupt/tool call),
        # return it in the same shape the frontend expects.
        if "agent" in last_event:
            agent_messages = last_event["agent"].get("messages", [])
            if agent_messages:
                last_msg = agent_messages[-1]
                if hasattr(last_msg, "content"):
                    content = last_msg.content
                    if isinstance(content, list):
                        text_chunks = []
                        for part in content:
                            if isinstance(part, dict) and part.get("type") == "text":
                                text_chunks.append(part.get("text", ""))
                        content = "\n".join(chunk for chunk in text_chunks if chunk).strip()
                    if isinstance(content, str) and content.strip():
                        return {
                            "thread_id": thread_id,
                            "status": "awaiting_approval",
                            "generated_post": content,
                            "action_required": "Reply with 'yes' to approve or 'no' to provide feedback",
                            "next_step": f"POST /resume?thread_id={thread_id}&reply=yes (or no)"
                        }
        
        return {
            "thread_id": thread_id,
            "status": "in_progress",
            "events": str(last_event),
            "next": list(current_state.next) if current_state.next else None
        }
    
    except Exception as e:
        import traceback
        return {
            "thread_id": thread_id,
            "status": "error",
            "error": str(e),
            "traceback": traceback.format_exc()
        }


@app.get("/health")
def health_check():
    return {"status": "ok"}



builder = StateGraph(PostState)

# -------------------
# Nodes
# -------------------
builder.add_node("agent", agent)
builder.add_node("tools", ToolNode(tools))
builder.add_node("ensure_auth", ensure_linkedin_auth)
builder.add_node("publish", publish_to_linkedin)


# Edges
# Start → agent (LLM decides whether to call tools)
builder.add_edge(START, "agent")

# After agent → check if tool call required
builder.add_conditional_edges(
    "agent",
    tools_condition
)

# NOTE: No static edge from "tools" - the Command(goto=...) from the tool handles routing
# When tool returns Command(goto="ensure_auth") or Command(goto="agent"), it will route accordingly

# After auth → publish to LinkedIn
builder.add_edge("ensure_auth", "publish")

# After publish → END
builder.add_edge("publish", END)

# -------------------
# Compile
# -------------------
workflow = builder.compile(checkpointer=InMemorySaver())




if __name__ == '__main__':
    import sys
    
    mode = sys.argv[1] if len(sys.argv) > 1 else "cli"
    
    if mode == "server":
        # Run FastAPI server for full OAuth flow
        port = int(os.getenv("PORT", "8000"))
        print(f"🚀 Starting server at http://localhost:{port}")
        print("\nAPI Endpoints:")
        print("  POST /start?topic=<topic>  - Start workflow")
        print("  POST /resume?thread_id=<id>&reply=<reply>  - Resume with reply")
        print("  GET  /callback  - LinkedIn OAuth callback")
        print(f"\nSwagger docs: http://localhost:{port}/docs")
        uvicorn.run(app, host="0.0.0.0", port=port)
    
    else:
        # CLI mode with background server for OAuth callback
        print("🔧 Running in CLI mode with OAuth support")
        print("-" * 50)
        
        # Start FastAPI server in background thread for OAuth callback
        def run_server():
            uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")
        
        server_thread = threading.Thread(target=run_server, daemon=True)
        server_thread.start()
        time.sleep(1)  # Wait for server to start
        print("📡 Background server started for OAuth callback")
        print("-" * 50)
        
        config = {"configurable": {"thread_id": "thread-1"}}

        # Initial input
        prompt_input = input("Enter the prompt: ")
        
        # Create descriptive run name for LangSmith
        short_topic = prompt_input[:50].replace(" ", "_") if len(prompt_input) > 50 else prompt_input.replace(" ", "_")
        run_name = f"LinkedIn_Post_{short_topic}"
        
        # Add run_name and metadata to config for better LangSmith tracing
        config["run_name"] = run_name
        config["metadata"] = {
            "prompt": prompt_input,
            "mode": "CLI",
            "workflow": "linkedin_post_generator"
        }
        config["tags"] = ["linkedin", "post-generator", "cli-mode"]
        
        input_data = {
            "messages": [
                HumanMessage(content=prompt_input)
            ]
        }

        while True:
            stream = workflow.stream(input_data, config=config)
            
            for event in stream:
                # Clean output - only show relevant info
                for node_name, node_data in event.items():
                    if node_name == "agent":
                        print("\n🤖 Agent processing request...")
                    elif node_name == "tools":
                        # Show approved/rejected status
                        if "response" in node_data:
                            print("\n✅ Post approved!")
                    elif node_name == "ensure_auth":
                        if "access_token" in node_data:
                            print("\n🔑 Authentication successful!")
                    elif node_name == "publish":
                        # Check for success message
                        messages = node_data.get("messages", [])
                        for msg in messages:
                            if hasattr(msg, 'content') and "successfully" in msg.content.lower():
                                print(f"\n{msg.content}")
                    elif node_name == "__interrupt__":
                        pass  # Handled separately below

                if "__interrupt__" in event:
                    interrupt_value = event["__interrupt__"][0].value
                    
                    # Check if it's OAuth interrupt
                    if isinstance(interrupt_value, dict) and interrupt_value.get("type") == "linkedin_auth_required":
                        oauth_state = interrupt_value.get("oauth_state")
                        
                        # Mask client_id in URL for display
                        display_url = re.sub(r"client_id=[a-zA-Z0-9]+", "client_id=[HIDDEN]", interrupt_value['url'])
                        
                        print("\n" + "=" * 50)
                        print("🔐 LinkedIn Authentication Required")
                        print(f"\nURL: {display_url}")
                        print("=" * 50)
                        
                        open_browser = input("\nOpen browser for LinkedIn auth? (yes/no): ").strip().lower()
                        if open_browser == "yes":
                            webbrowser.open(interrupt_value['url'])  # Use actual URL for browser
                            print("\n⏳ Waiting for LinkedIn authentication...")
                            print("   (Complete the login in your browser)")
                            
                            # Wait for callback to populate pending_auth
                            timeout = 120  # 2 minutes timeout
                            start_time = time.time()
                            
                            while oauth_state not in pending_auth:
                                if time.time() - start_time > timeout:
                                    print("\n❌ Timeout waiting for authentication")
                                    input_data = None
                                    break
                                time.sleep(1)
                                print(".", end="", flush=True)
                            
                            if oauth_state in pending_auth:
                                token_data = pending_auth.pop(oauth_state)
                                print(f"\n\n✅ LinkedIn authenticated successfully!")
                                input_data = Command(resume=token_data)
                            else:
                                break
                        else:
                            print("⏭️  Skipping LinkedIn posting (mock mode)")
                            input_data = Command(resume={"access_token": "mock", "person_id": "mock"})
                    else:
                        # Regular text interrupt (approval/feedback)
                        # Handle new dict-based interrupt format
                        if isinstance(interrupt_value, dict) and interrupt_value.get("type") == "post_approval":
                            post_text = interrupt_value.get("post", "")
                            print("\n" + "=" * 50)
                            print("📝 GENERATED POST")
                            print("=" * 50)
                            print(f"\n{post_text}\n")
                            print("=" * 50)
                            user_reply = input("Approve? (yes/no): ")
                            # Pass back BOTH the answer AND the post to preserve it
                            input_data = Command(resume={"answer": user_reply, "post": post_text})
                        elif isinstance(interrupt_value, dict) and interrupt_value.get("type") == "feedback":
                            print("\n📝 Post rejected. Please provide feedback:")
                            feedback = input("Your feedback: ")
                            input_data = Command(resume={"feedback": feedback})
                        elif "Do you approve this post?" in str(interrupt_value):
                            # Legacy format fallback
                            print("\n" + "=" * 50)
                            print("📝 GENERATED POST")
                            print("=" * 50)
                            post_text = str(interrupt_value).replace("Do you approve this post? (yes/no)\n\n", "")
                            print(f"\n{post_text}\n")
                            print("=" * 50)
                            user_reply = input("Approve? (yes/no): ")
                            input_data = Command(resume=user_reply)
                        elif "feedback" in str(interrupt_value).lower():
                            print("\n📝 Post rejected. Please provide feedback:")
                            user_reply = input("Your feedback: ")
                            input_data = Command(resume=user_reply)
                        else:
                            user_reply = input("Your reply: ")
                            input_data = Command(resume=user_reply)
                    break
            else:
                # Stream completed without interrupt - we're done
                print("\n✅ Workflow completed!")
                break
            
            if input_data is None:
                print("\n❌ Workflow cancelled")
                break
