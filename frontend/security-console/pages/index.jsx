import React, { useCallback, useEffect, useState } from 'react';
import Login from '../components/Login';
import Navbar from '../components/Navbar';
import MetricCards from '../components/MetricCards';
import PipelineFlow from '../components/PipelineFlow';
import IncidentLog from '../components/IncidentLog';
import ForensicModal from '../components/ForensicModal';
import ReviewQueue from '../components/ReviewQueue';
import FeedbackList from '../components/FeedbackList';
import AttackSimulator from '../components/AttackSimulator';
import ManualTester from '../components/ManualTester';
import SessionList, { SessionSummary } from '../components/SessionList';
import { api, AuthError, loadToken, saveToken } from '../lib/api';

const EMPTY_STATS = { total_incidents: 0, avg_latency_ms: 0, by_layer: {}, by_decision: {}, pending_reviews: 0, tainted_sessions: 0 };

export default function SecurityConsole() {
  const [token, setToken] = useState(null);
  const [user, setUser] = useState('');
  const [ready, setReady] = useState(false);
  const [tab, setTab] = useState('overview');
  const [incidents, setIncidents] = useState([]);
  const [stats, setStats] = useState(EMPTY_STATS);
  const [health, setHealth] = useState(null);
  const [sessions, setSessions] = useState([]);
  const [pending, setPending] = useState([]);
  const [history, setHistory] = useState([]);
  const [feedback, setFeedback] = useState([]);
  const [selected, setSelected] = useState(null);
  const [open, setOpen] = useState(null);
  const [online, setOnline] = useState(true);

  useEffect(() => {
    const t = loadToken();
    if (t) {
      setToken(t);
      setUser(sessionStorage.getItem('fw_user') || 'security_admin');
    }
    setReady(true);
  }, []);

  const logout = useCallback(() => {
    saveToken(null);
    try { sessionStorage.removeItem('fw_user'); } catch (e) { /* ignore */ }
    setToken(null);
  }, []);

  const refresh = useCallback(async () => {
    try {
      const [inc, st, he, ses, pen, all, fb] = await Promise.all([
        api('/console/incidents?limit=100'),
        api('/console/stats'),
        api('/console/health'),
        api('/console/sessions?include_exposed=true'),
        api('/chat/review?status=pending'),
        api('/chat/review?status=all'),
        api('/console/feedback?limit=30'),
      ]);
      setIncidents(inc);
      setStats(st);
      setHealth(he);
      setSessions(ses);
      setPending(pen);
      setHistory(all.filter((i) => i.status !== 'pending').slice(0, 30));
      setFeedback(fb);
      setOnline(true);
    } catch (e) {
      if (e instanceof AuthError) logout();
      else setOnline(false);
    }
  }, [logout]);

  useEffect(() => {
    if (!token) return undefined;
    refresh();
    const id = setInterval(refresh, 2500);
    return () => clearInterval(id);
  }, [token, refresh]);

  const clearLogs = async () => {
    if (!window.confirm('Xóa toàn bộ nhật ký sự cố?')) return;
    try {
      await api('/console/clear', { method: 'POST' });
      setSelected(null);
      setOpen(null);
      refresh();
    } catch (e) {
      alert(`Không xóa được: ${e.message}`);
    }
  };

  const choose = (incident) => {
    setSelected(incident);
    setOpen(incident);
  };

  if (!ready) return null;
  if (!token) {
    return (
      <Login
        onLoggedIn={(t, name) => {
          saveToken(t);
          try { sessionStorage.setItem('fw_user', name); } catch (e) { /* ignore */ }
          setUser(name);
          setToken(t);
        }}
      />
    );
  }

  return (
    <div>
      <Navbar tab={tab} onTab={setTab} isOnline={online} health={health} pending={pending.length} user={user} onLogout={logout} onClear={clearLogs} />
      <main className="page">
        {!online && <div className="alert">Không kết nối được API ở cổng 8000. Chạy: <code>uvicorn api.main:app --port 8000</code></div>}

        {tab === 'overview' && (
          <>
            <MetricCards stats={stats} />
            <PipelineFlow activeLayer={selected ? selected.blocked_by_layer : null} counts={stats.by_layer || {}} health={health} />
            <div className="grid two">
              <IncidentLog incidents={incidents} selectedId={selected?.id} onSelect={choose} limit={6} title="Sự cố mới nhất" />
              <SessionSummary sessions={sessions} />
            </div>
          </>
        )}

        {tab === 'incidents' && (
          <>
            <IncidentLog incidents={incidents} selectedId={selected?.id} onSelect={choose} />
            <FeedbackList items={feedback} />
          </>
        )}

        {tab === 'sessions' && <SessionList sessions={sessions} />}

        {tab === 'review' && <ReviewQueue pending={pending} history={history} onChanged={refresh} />}

        {tab === 'try' && <ManualTester onRan={refresh} health={health} />}

        {tab === 'lab' && <AttackSimulator onRan={refresh} />}
      </main>

      <ForensicModal incident={open} onClose={() => setOpen(null)} />
    </div>
  );
}
