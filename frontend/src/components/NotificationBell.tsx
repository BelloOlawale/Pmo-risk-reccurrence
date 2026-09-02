import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';

import { api } from '../api/client';
import type { Notification } from '../api/types';
import { useApi } from '../hooks/useApi';
import { formatDateTime } from '../utils/format';

export function NotificationBell() {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);

  const { data, setData } = useApi(() => api.get<Notification[]>('/api/notifications'), []);

  useEffect(() => {
    function onClick(e: MouseEvent) {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener('mousedown', onClick);
    return () => document.removeEventListener('mousedown', onClick);
  }, []);

  const notifications = data ?? [];
  const unread = notifications.filter((n) => !n.read).length;

  async function markRead(id: number) {
    try {
      const updated = await api.post<Notification>(`/api/notifications/${id}/read`);
      setData(notifications.map((n) => (n.id === updated.id ? updated : n)));
    } catch {
      // ignore — the bell is best-effort
    }
  }

  return (
    <div className="bell-wrap" ref={wrapRef}>
      <button className="bell-btn" onClick={() => setOpen((o) => !o)} aria-label="Notifications">
        <svg
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9" />
          <path d="M13.73 21a2 2 0 0 1-3.46 0" />
        </svg>
      </button>
      {unread > 0 ? <span className="bell-count">{unread}</span> : null}
      {open ? (
        <div className="bell-dropdown">
          {notifications.length === 0 ? (
            <div className="empty-state">No notifications</div>
          ) : (
            notifications.map((n) => (
              <div
                key={n.id}
                className={`notification-item${n.read ? '' : ' unread'}`}
                onClick={() => markRead(n.id)}
              >
                <div className="notification-title">{n.title}</div>
                <div className="notification-body">{n.body}</div>
                <div className="notification-time">{formatDateTime(n.created_at)}</div>
                {n.risk_id !== null ? (
                  <Link to={`/risks/${n.risk_id}`} onClick={(e) => e.stopPropagation()}>
                    View risk →
                  </Link>
                ) : null}
              </div>
            ))
          )}
        </div>
      ) : null}
    </div>
  );
}
