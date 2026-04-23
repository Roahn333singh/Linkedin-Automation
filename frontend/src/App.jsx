import { useState, useEffect } from 'react';
import axios from 'axios';
import {
  Bot, Send, CheckCircle2, XCircle, Network,
  Loader2, MessageSquare, LayoutDashboard,
  Settings, History, Sparkles, Zap, TriangleAlert,
  Brain, PenLine, UserCheck, Link2, Rocket, Clock,
  ThumbsUp, MessageCircle, Repeat
} from 'lucide-react';
import './App.css';

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'
});

/* ── Step definitions (matches the LangGraph nodes) ───────── */
const STEPS = [
  { id: 'start',    label: 'Received',          icon: Sparkles,   desc: 'Workflow initiated'               },
  { id: 'agent',    label: 'Agent Thinking',     icon: Brain,      desc: 'LLM orchestrating actions'       },
  { id: 'tools',    label: 'Drafting Post',      icon: PenLine,    desc: 'Generating LinkedIn content'     },
  { id: 'approval', label: 'Awaiting Approval',  icon: UserCheck,  desc: 'Human-in-the-loop checkpoint'   },
  { id: 'auth',     label: 'LinkedIn Auth',      icon: Link2,      desc: 'OAuth authorization required'   },
  { id: 'publish',  label: 'Publishing',         icon: Rocket,     desc: 'Sending post to LinkedIn'       },
  { id: 'done',     label: 'Completed',          icon: CheckCircle2, desc: 'Post is live!'               },
];

const STATE_TO_STEP = {
  idle: null, loading: 'agent', approval: 'approval',
  feedback: 'approval', auth: 'auth', done: 'done', error: null,
};

/* ── Tiny helpers ──────────────────────────────────────────── */
function StepTracker({ currentState }) {
  const activeStepId = STATE_TO_STEP[currentState];
  const activeIdx = STEPS.findIndex(s => s.id === activeStepId);

  return (
    <div className="step-tracker">
      {STEPS.map((step, i) => {
        const StepIcon = step.icon;
        const isDone    = activeIdx > i;
        const isActive  = activeIdx === i;
        const isPending = activeIdx < i;

        return (
          <div key={step.id} className="step-row">
            <div className={`step-icon-wrap ${isDone ? 'done' : isActive ? 'active' : 'pending'}`}>
              {isDone ? (
                <CheckCircle2 size={16} />
              ) : isActive ? (
                <Loader2 size={16} className="spin" />
              ) : (
                <StepIcon size={16} />
              )}
            </div>
            <div className="step-info">
              <span className={`step-label ${isActive ? 'step-label-active' : isPending ? 'step-label-pending' : ''}`}>
                {step.label}
              </span>
              {isActive && <span className="step-desc">{step.desc}</span>}
            </div>
            {i < STEPS.length - 1 && (
              <div className={`step-connector ${isDone ? 'connector-done' : ''}`} />
            )}
          </div>
        );
      })}
    </div>
  );
}

/* ── Main App ──────────────────────────────────────────────── */
export default function App() {
  const [topic,         setTopic]         = useState('');
  const [threadId,      setThreadId]      = useState(null);
  const [uiState,       setUiState]       = useState('idle');
  const [generatedPost, setGeneratedPost] = useState('');
  const [authUrl,       setAuthUrl]       = useState('');
  const [feedback,      setFeedback]      = useState('');
  const [error,         setError]         = useState('');
  const [log,           setLog]           = useState([]);   // activity log entries

  const addLog = (msg, type = 'info') =>
    setLog(prev => [...prev, { msg, type, ts: new Date().toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit' }) }]);

  /* ── handle /start ─────────────────────────────────────── */
  const startWorkflow = async (e) => {
    e.preventDefault();
    if (!topic.trim()) return;

    setUiState('loading');
    setLog([]);
    setError('');
    setGeneratedPost('');
    addLog('Workflow started — sending topic to agent', 'info');
    addLog('Agent node activated — invoking LLM with tools', 'info');

    try {
      const { data } = await api.post('/start', null, { params: { topic } });

      addLog('LangGraph stream complete — processing interrupt', 'info');

      /* ── Parse the interrupt payload ──────────────────── */
      // The backend returns `generated_post` which can be:
      //   a) a dict: { type: "post_approval", question: "...", post: "..." }
      //   b) a plain string (legacy)
      const raw = data.generated_post;
      let postText = '';

      if (typeof raw === 'object' && raw !== null) {
        // Dict format — pull the actual post text
        postText = raw.post ?? raw.message ?? JSON.stringify(raw);
      } else if (typeof raw === 'string') {
        postText = raw;
      }

      if (data.status === 'awaiting_approval' && postText) {
        setThreadId(data.thread_id);
        setGeneratedPost(postText);
        addLog('Post draft ready — human review required', 'success');
        setUiState('approval');
      } else {
        throw new Error(`Unexpected response: ${JSON.stringify(data)}`);
      }
    } catch (err) {
      const msg = err.response?.data?.error || err.message || 'Unknown error';
      addLog(`Error: ${msg}`, 'error');
      setError(msg);
      setUiState('error');
    }
  };

  const resume = async (reply, logMsg) => {
    setUiState('loading');
    if (logMsg) addLog(logMsg, 'info');

    const replyPayload = typeof reply === 'object' ? JSON.stringify(reply) : String(reply);

    try {
      const { data } = await api.post('/resume', null, {
        params: { thread_id: threadId, reply: replyPayload }
      });

      if (data.status === 'awaiting_approval') {
        const raw = data.generated_post;
        let postText = typeof raw === 'object' && raw !== null
          ? (raw.post ?? raw.message ?? JSON.stringify(raw))
          : String(raw ?? '');
        setGeneratedPost(postText);
        addLog('Revised draft ready — review requested', 'success');
        setUiState('approval');
      } else if (data.status === 'awaiting_linkedin_auth') {
        setAuthUrl(data.auth_url ?? data.auth_url);
        addLog('LinkedIn OAuth required — awaiting user authorization', 'warn');
        setUiState('auth');
      } else if (data.status === 'completed') {
        addLog('Post published successfully to LinkedIn! 🎉', 'success');
        setUiState('done');
      } else if (data.status === 'awaiting_feedback') {
        addLog('Post rejected — please provide revision instructions', 'warn');
        setUiState('feedback');
      } else if (data.status === 'error') {
        addLog(`Backend error: ${data.error}`, 'error');
        setError(data.error);
        setUiState('error');
      } else {
        throw new Error(`Unexpected state: ${JSON.stringify(data)}`);
      }
    } catch (err) {
      const msg = err.response?.data?.error || err.message;
      addLog(`Error: ${msg}`, 'error');
      setError(msg);
      setUiState('error');
    }
  };

  const reset = () => {
    setTopic(''); setThreadId(null); setUiState('idle');
    setGeneratedPost(''); setAuthUrl(''); setError('');
    setFeedback(''); setLog([]);
  };

  /* ── Auto-listen for LinkedIn Auth ─────────────────────── */
  useEffect(() => {
    const handleMessage = (event) => {
      console.log('Received window message:', event.data);
      if (event.data?.type === 'LINKEDIN_AUTH_SUCCESS') {
        addLog('Received auth success from popup — resuming...', 'success');
        resume('done', 'LinkedIn OAuth successful — automatically resuming workflow');
      }
    };
    
    window.addEventListener('message', handleMessage);
    return () => window.removeEventListener('message', handleMessage);
  }, [threadId, uiState]); // re-bind when state changes so it captures current resume function

  /* ── Views ─────────────────────────────────────────────── */
  const renderView = () => {
    switch (uiState) {
      case 'idle': return (
        <div className="card fade-up">
          <div className="card-header">
            <h2 className="card-title"><Sparkles size={18} color="var(--accent-light)" />New Post Request</h2>
          </div>
          <form onSubmit={startWorkflow}>
            <label className="field-label">What should the post be about?</label>
            <textarea
              className="field"
              value={topic}
              onChange={e => setTopic(e.target.value)}
              placeholder="e.g. How agentic AI is changing software development in 2025..."
            />
            
            <div className="quick-prompts">
              <span className="quick-prompts-label">Quick Prompts:</span>
              <button type="button" className="quick-prompt-btn" onClick={() => setTopic("The future of Agentic AI and how it replaces traditional coding.")}>🚀 Future of AI</button>
              <button type="button" className="quick-prompt-btn" onClick={() => setTopic("Key leadership lessons from scaling a startup to 100 employees.")}>💡 Leadership Advice</button>
              <button type="button" className="quick-prompt-btn" onClick={() => setTopic("Why transitioning from monolith to microservices isn't always the right choice.")}>🛠️ Tech Architecture</button>
            </div>

            <div className="btn-row">
              <button type="submit" className="btn btn-primary ai-glow-btn" disabled={!topic.trim()}>
                <Zap size={16} /> Generate Draft
              </button>
            </div>
          </form>
        </div>
      );

      case 'loading': return (
        <div className="card center-view fade-up">
          <div className="spinner-wrap">
            <div className="spinner-glow" />
            <Loader2 size={48} className="spin" style={{ color: '#60a5fa', position: 'relative', zIndex: 2 }} />
          </div>
          <h2 style={{ fontSize: '1.5rem', marginBottom: '0.4rem' }}>Agent Working</h2>
          <p className="text-muted" style={{ fontSize: '0.9rem' }}>Running LangGraph workflow nodes...</p>
        </div>
      );

      case 'approval': return (
        <div className="card fade-up ai-active-border">
          <div className="card-header">
            <h2 className="card-title"><UserCheck size={18} color="#fbbf24" />Human Review Required</h2>
            <span className="chip chip-amber">⏳ Awaiting Decision</span>
          </div>
          
          <label className="field-label" style={{ marginBottom: '0.75rem' }}>Generated Draft Preview</label>
          
          <div className="linkedin-mock">
            <div className="li-header">
              <div className="li-avatar">
                <Bot size={20} color="#fff" />
              </div>
              <div className="li-meta">
                <div className="li-name">AgentForge AI</div>
                <div className="li-headline">Automated LinkedIn Creator • AI Assistant</div>
                <div className="li-time">Just now • 🌐</div>
              </div>
            </div>
            
            <div className="li-body">
              {generatedPost}
            </div>
            
            <div className="li-divider"></div>
            
            <div className="li-actions">
              <div className="li-action"><ThumbsUp size={18} /> Like</div>
              <div className="li-action"><MessageCircle size={18} /> Comment</div>
              <div className="li-action"><Repeat size={18} /> Repost</div>
              <div className="li-action"><Send size={18} /> Send</div>
            </div>
          </div>

          <div className="btn-row" style={{ marginTop: '1.5rem' }}>
            <button className="btn btn-danger" onClick={() => setUiState('feedback')}>
              <XCircle size={16} /> Request Edits
            </button>
            <button className="btn btn-success" onClick={() => resume({ answer: 'yes', post: generatedPost }, 'User approved ✅ — routing to auth/publish')}>
              <CheckCircle2 size={16} /> Approve &amp; Publish
            </button>
          </div>
        </div>
      );

      case 'feedback': return (
        <div className="card fade-up">
          <div className="card-header">
            <h2 className="card-title"><MessageSquare size={18} color="#f87171" />Revision Instructions</h2>
          </div>
          <p className="text-muted" style={{ marginBottom: '1.25rem', fontSize: '0.9rem' }}>
            The agent will regenerate the post with your instructions applied.
          </p>
          <label className="field-label">Your Feedback</label>
          <textarea
            className="field"
            value={feedback}
            onChange={e => setFeedback(e.target.value)}
            placeholder="e.g. Make it shorter, more direct, end with a hook question, add hashtags..."
          />
          <div className="btn-row">
            <button className="btn btn-ghost" onClick={() => setUiState('approval')}>Cancel</button>
            <button className="btn btn-primary"
              disabled={!feedback.trim()}
              onClick={() => {
                resume(feedback, `Sending feedback → agent for revision`);
                setFeedback('');
              }}>
              <Send size={16} /> Regenerate
            </button>
          </div>
        </div>
      );

      case 'auth': return (
        <div className="card center-view fade-up" style={{ gap: '0.85rem' }}>
          <div className="spinner-wrap" style={{ marginBottom: '0.25rem' }}>
            <div className="spinner-glow" style={{ background: 'rgba(59,130,246,0.25)' }} />
            <div className="icon-ring" style={{ background: 'rgba(10,102,194,0.12)', border: '1px solid rgba(10,102,194,0.35)', position: 'relative', zIndex: 2 }}>
              <Network size={32} color="#60a5fa" />
            </div>
          </div>
          <h2 style={{ fontSize: '1.6rem' }}>LinkedIn Authorization</h2>
          <p className="text-muted" style={{ maxWidth: 360, fontSize: '0.9rem', lineHeight: 1.6 }}>
            The agent needs permission to publish on your behalf. Complete the OAuth flow below.
          </p>
          <button className="btn btn-primary" style={{ marginTop: '0.25rem' }}
            onClick={() => window.open(authUrl, '_blank', 'width=580,height=680')}>
            <Network size={16} /> Open LinkedIn Auth
          </button>
          <div className="auth-confirm-box" style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '0.8rem', background: 'transparent', border: 'none' }}>
            <div className="loader" style={{ width: 18, height: 18, borderWidth: 2 }}></div>
            <p className="text-muted" style={{ fontSize: '0.85rem', textAlign: 'center' }}>
              Waiting for you to complete authorization...<br/>
              <span style={{ fontSize: '0.75rem', opacity: 0.7 }}>(This will automatically continue when done)</span>
            </p>
            <div style={{ height: 1, width: '100%', background: 'rgba(255,255,255,0.05)', margin: '0.5rem 0' }} />
            <button className="btn btn-ghost" style={{ fontSize: '0.75rem' }} 
              onClick={() => resume('done', 'Manual resume after auth')}>
              Already authorized? Click here to continue manually
            </button>
          </div>
        </div>
      );

      case 'done': return (
        <div className="card center-view fade-up">
          <div className="icon-ring" style={{ width: 90, height: 90, background: 'rgba(16,185,129,0.1)', border: '1px solid rgba(16,185,129,0.3)', boxShadow: '0 0 40px rgba(16,185,129,0.12)', marginBottom: '1.25rem' }}>
            <CheckCircle2 size={42} color="#34d399" />
          </div>
          <h2 style={{ fontSize: '1.8rem', marginBottom: '0.4rem' }}>Published!</h2>
          <p className="text-muted" style={{ marginBottom: '2rem', fontSize: '0.9rem' }}>Your post is now live on LinkedIn.</p>
          <button className="btn btn-primary" onClick={reset}>
            <LayoutDashboard size={16} /> Back to Dashboard
          </button>
        </div>
      );

      case 'error': return (
        <div className="card fade-up" style={{ borderColor: 'rgba(244,63,94,0.3)' }}>
          <div className="card-header">
            <h2 className="card-title" style={{ color: '#fb7185' }}><TriangleAlert size={18} />Workflow Error</h2>
          </div>
          <pre className="error-block">{error}</pre>
          <div className="btn-row">
            <button className="btn btn-ghost" onClick={reset}>Dismiss &amp; Restart</button>
          </div>
        </div>
      );

      default: return null;
    }
  };

  return (
    <>
      <div className="bg-canvas">
        <div className="blob blob-1" />
        <div className="blob blob-2" />
        <div className="blob blob-3" />
      </div>

      <div className="app-shell">
        {/* ── Sidebar ───────────────────────── */}
        <aside className="panel sidebar">
          <div className="brand">
            <div className="brand-logo"><Bot size={20} /></div>
            <div>
              <div className="brand-name">Agent<span>Forge</span></div>
              <div className="brand-tag">AI Automation</div>
            </div>
          </div>

          <nav className="nav">
            <div className={`nav-item ${uiState === 'idle' ? 'active' : ''}`} onClick={reset}>
              <LayoutDashboard size={17} /> Dashboard
            </div>
            <div className="nav-item">
              <History size={17} /> Run History
            </div>
            <div className="nav-bottom">
              <div className="nav-item"><Settings size={17} /> Settings</div>
            </div>
          </nav>
        </aside>

        {/* ── Main ──────────────────────────── */}
        <main className="panel main">
          <header className="page-header">
            <h1 className="page-title gradient-text">LinkedIn Cortex</h1>
            <p className="page-subtitle">Multi-step agentic reasoning — from idea to published post.</p>
          </header>

          <div className="main-body">

            {/* Left: step tracker + content */}
            <div className="left-col">
              {/* Step tracker (only when active) */}
              {uiState !== 'idle' && <StepTracker currentState={uiState} />}

              {/* Primary view */}
              <div className="view-area">{renderView()}</div>
            </div>

            {/* Right: activity log */}
            {log.length > 0 && (
              <div className="right-col">
                <div className="log-panel">
                  <h3 className="log-title"><Clock size={14} /> Activity Log</h3>
                  <div className="log-entries">
                    {log.map((entry, i) => (
                      <div key={i} className={`log-entry log-${entry.type}`}>
                        <span className="log-ts">{entry.ts}</span>
                        <span className="log-msg">{entry.msg}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}
          </div>
        </main>
      </div>
    </>
  );
}
