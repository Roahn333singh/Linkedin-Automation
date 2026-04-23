# AgentForge: LinkedIn AI Automation

A professional-grade, multi-step AI agent that drafts, iterates on, and automatically publishes posts to your LinkedIn account using a human-in-the-loop (HITL) approval system. 

## 🌟 Features
- **Agentic Generation**: Powered by LangGraph and Gemini for high-quality post drafting using tailored, non-cliche prompts.
- **Human-in-the-loop**: Full control over what gets posted. Review the draft, provide feedback for revisions, and approve it before publishing.
- **LinkedIn Integration**: Custom built-in OAuth flow. Directly authorize the application and let the backend securely publish on your behalf.
- **Glassmorphism UI**: A stunning, ultra-premium React frontend with beautiful micro-animations, built from scratch with custom CSS.

## 🚀 Architecture
- **Frontend**: React + Vite + Lucide React. Uses standard CSS for complex glass effects.
- **Backend**: FastAPI + LangGraph + Langchain. Orchestrates the AI agent workflow and handles the OAuth callback from LinkedIn.

## 💻 Getting Started

### 1. Backend Setup
1. Navigate to the `backend` directory.
2. Ensure you have the `.venv` created and all dependencies installed.
3. Your `.env` must contain:
   - `GOOGLE_API_KEY`
   - `CLIENT_ID` (LinkedIn OAuth)
   - `CLIENT_SECRET` (LinkedIn OAuth)
   - `REDIRECT_URI` (Usually `http://localhost:8000/callback`)
4. Start the server:
   ```bash
   source .venv/bin/activate
   python LinkedinRun.py server
   ```
   *The backend will run on `http://localhost:8000`.*

### 2. Frontend Setup
1. Navigate to the `frontend` directory.
2. Install dependencies (already completed in this repo).
3. Start the dev server:
   ```bash
   npm run dev
   ```
   *The frontend will run on `http://localhost:5173`.*

## 🧠 Workflow
1. **Initiation**: Enter a topic on the dashboard.
2. **Drafting**: The LangGraph agent generates a tailored LinkedIn post.
3. **Approval**: You are presented with the draft. You can either approve or reject with specific feedback.
4. **OAuth**: Once approved, the agent generates an authorization link. Complete the login flow in a new window.
5. **Publish**: Return to the dashboard and confirm. The post is pushed directly to your LinkedIn feed.

## 🌐 Deploy on DigitalOcean (App Platform)

### Goal
Deploy a live backend URL that your friend's project can call directly.

### 1) Production-ready config in this repo
- Frontend now reads backend URL from `VITE_API_BASE_URL`.
- Backend CORS now accepts `FRONTEND_URL` (plus localhost for dev).
- Backend has a health endpoint: `GET /health`.
- Backend dependencies are listed in `backend/requirements.txt`.
- App Platform spec file is available at `.do/app.yaml`.

### 2) Push to GitHub
Push this project to a GitHub repo (required by App Platform).

### 3) Create the app
In DigitalOcean App Platform:
1. Create App from GitHub repo.
2. Either:
   - import `.do/app.yaml`, or
   - create two components manually:
     - `backend` (Python service, source `backend`, run `python LinkedinRun.py server`)
     - `frontend` (Static site, source `frontend`, build `npm run build`, output `dist`)

### 4) Set environment variables
Backend:
- `GOOGLE_API_KEY`
- `CLIENT_ID`
- `CLIENT_SECRET`
- `REDIRECT_URI` = `https://<your-backend-domain>/callback`
- `FRONTEND_URL` = `https://<your-frontend-domain>`

Frontend:
- `VITE_API_BASE_URL` = `https://<your-backend-domain>`

### 5) LinkedIn OAuth setup
In your LinkedIn Developer App, add this redirect URL:
- `https://<your-backend-domain>/callback`

### 6) Share API URL with friend
Give your friend only the backend base URL:
- `https://<your-backend-domain>`

They can call:
- `POST /start?topic=<topic>`
- `POST /resume?thread_id=<id>&reply=<reply>`

### 7) Quick smoke test
1. Open frontend URL.
2. Generate a post.
3. Approve and complete LinkedIn auth.
4. Confirm publish completes.
