import React, { useState, useEffect, useCallback } from 'react';
import {
  Share2, Link2, Unlink, Loader2, CheckCircle2, XCircle, AlertCircle,
  RefreshCw, Send, RotateCcw, X, Film,
} from 'lucide-react';
import {
  api,
  PlatformCapability,
  ConnectedAccountResponse,
  SocialPostResponse,
} from '../api/client';

export const PublishingDashboard: React.FC = () => {
  const [capabilities, setCapabilities] = useState<PlatformCapability[]>([]);
  const [accounts, setAccounts] = useState<ConnectedAccountResponse[]>([]);
  const [posts, setPosts] = useState<SocialPostResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [caps, accs, psts] = await Promise.all([
        api.getPublishingCapabilities(),
        api.getConnectedAccounts(),
        api.listSocialPosts({ limit: 100 }),
      ]);
      setCapabilities(caps.data.platforms);
      setAccounts(accs.data.accounts);
      setPosts(psts.data.posts);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const handle = window.setInterval(() => void refresh(), 15000);
    return () => window.clearInterval(handle);
  }, [refresh]);

  const handleDisconnect = async (accountId: string) => {
    setActionLoading(accountId);
    try {
      await api.disconnectAccount(accountId);
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setActionLoading(null);
    }
  };

  const handleRetry = async (postId: string) => {
    setActionLoading(`retry-${postId}`);
    try {
      await api.retrySocialPost(postId);
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setActionLoading(`retry-${postId}`);
    }
  };

  const handleCancel = async (postId: string) => {
    setActionLoading(`cancel-${postId}`);
    try {
      await api.cancelSocialPost(postId);
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setActionLoading(`cancel-${postId}`);
    }
  };

  const statusColor = (status: string): string => {
    switch (status) {
      case 'published': return 'text-emerald-400';
      case 'publishing': return 'text-indigo-400';
      case 'failed': return 'text-rose-400';
      case 'cancelled': return 'text-amber-400';
      case 'draft': return 'text-slate-400';
      case 'ready': return 'text-cyan-400';
      case 'queued': return 'text-violet-400';
      default: return 'text-slate-400';
    }
  };

  const statusIcon = (status: string) => {
    switch (status) {
      case 'published': return <CheckCircle2 className="w-3 h-3" />;
      case 'publishing': return <Loader2 className="w-3 h-3 animate-spin" />;
      case 'failed': return <XCircle className="w-3 h-3" />;
      case 'cancelled': return <X className="w-3 h-3" />;
      default: return <Film className="w-3 h-3" />;
    }
  };

  return (
    <div className="flex flex-col gap-4 h-full overflow-y-auto">
      {error && (
        <div className="flex items-center gap-2 px-4 py-3 text-rose-400 text-xs bg-rose-950/30 border border-rose-900/50 rounded-lg">
          <AlertCircle className="w-4 h-4 shrink-0" />
          <span>{error}</span>
          <button onClick={() => setError(null)} className="ml-auto text-slate-500 hover:text-slate-300">×</button>
        </div>
      )}

      {/* Platform Capability Matrix */}
      <div className="bg-slate-900/40 border border-slate-800 rounded-lg overflow-hidden">
        <div className="flex items-center gap-2 px-4 py-3 border-b border-slate-800 bg-slate-900/60">
          <Share2 className="w-4 h-4 text-indigo-400" />
          <h3 className="text-sm font-semibold text-slate-200">Platform Capability Matrix</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-slate-800 text-slate-500">
                <th className="px-3 py-2 text-left font-mono">Platform</th>
                <th className="px-3 py-2 text-center font-mono">Video</th>
                <th className="px-3 py-2 text-center font-mono">Caption</th>
                <th className="px-3 py-2 text-center font-mono">Title</th>
                <th className="px-3 py-2 text-center font-mono">Tags</th>
                <th className="px-3 py-2 text-center font-mono">Privacy</th>
                <th className="px-3 py-2 text-center font-mono">Thumb</th>
                <th className="px-3 py-2 text-center font-mono">Max Dur</th>
                <th className="px-3 py-2 text-left font-mono">Status</th>
              </tr>
            </thead>
            <tbody>
              {capabilities.map((cap) => (
                <tr key={cap.platform} className="border-b border-slate-800/60 hover:bg-slate-800/30">
                  <td className="px-3 py-2 font-mono text-slate-200 capitalize">{cap.platform}</td>
                  <td className="px-3 py-2 text-center">{cap.supports_video ? '✓' : '—'}</td>
                  <td className="px-3 py-2 text-center">{cap.supports_caption ? '✓' : '—'}</td>
                  <td className="px-3 py-2 text-center">{cap.supports_title ? '✓' : '—'}</td>
                  <td className="px-3 py-2 text-center">{cap.supports_hashtags ? '✓' : '—'}</td>
                  <td className="px-3 py-2 text-center">{cap.supports_privacy ? '✓' : '—'}</td>
                  <td className="px-3 py-2 text-center">{cap.supports_thumbnail ? '✓' : '—'}</td>
                  <td className="px-3 py-2 text-center text-slate-500">{cap.max_video_duration_seconds ? `${cap.max_video_duration_seconds}s` : '—'}</td>
                  <td className="px-3 py-2">
                    <span className={`text-[10px] font-mono font-semibold ${
                      cap.implementation_status === 'working' ? 'text-emerald-400' :
                      cap.implementation_status === 'partially_implemented' ? 'text-amber-400' :
                      cap.implementation_status === 'blocked' ? 'text-rose-400' : 'text-slate-500'
                    }`}>
                      {cap.implementation_status.replace(/_/g, ' ').toUpperCase()}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Connected Accounts */}
      <div className="bg-slate-900/40 border border-slate-800 rounded-lg overflow-hidden">
        <div className="flex items-center gap-2 px-4 py-3 border-b border-slate-800 bg-slate-900/60">
          <Link2 className="w-4 h-4 text-indigo-400" />
          <h3 className="text-sm font-semibold text-slate-200">Connected Accounts</h3>
          <span className="text-[10px] font-mono text-slate-500">({accounts.length})</span>
        </div>
        <div className="p-4">
          {accounts.length === 0 ? (
            <div className="flex flex-col items-center gap-2 text-slate-600 py-6">
              <Link2 className="w-6 h-6 opacity-30" />
              <span className="text-xs font-mono">No connected accounts</span>
              <span className="text-[10px] text-slate-700">Connect a platform via OAuth to start publishing</span>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
              {accounts.map((acc) => (
                <div key={acc.account_id} className="flex items-center gap-3 p-3 bg-slate-950/50 border border-slate-800 rounded-lg">
                  <div className="w-8 h-8 rounded bg-indigo-600/20 flex items-center justify-center text-indigo-400 text-xs font-bold uppercase">
                    {acc.platform.slice(0, 2)}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="text-xs font-mono text-slate-200 truncate">{acc.display_name}</div>
                    <div className="text-[10px] text-slate-500 capitalize">{acc.platform}</div>
                  </div>
                  <div className={`w-2 h-2 rounded-full ${acc.status === 'connected' ? 'bg-emerald-500' : 'bg-rose-500'}`} />
                  <button
                    onClick={() => handleDisconnect(acc.account_id)}
                    disabled={actionLoading === acc.account_id}
                    className="p-1 text-slate-500 hover:text-rose-400 transition-colors disabled:opacity-30"
                    title="Disconnect"
                  >
                    {actionLoading === acc.account_id ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Unlink className="w-3.5 h-3.5" />}
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Publishing Posts */}
      <div className="bg-slate-900/40 border border-slate-800 rounded-lg overflow-hidden flex-1">
        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800 bg-slate-900/60">
          <div className="flex items-center gap-2">
            <Send className="w-4 h-4 text-indigo-400" />
            <h3 className="text-sm font-semibold text-slate-200">Publishing Posts</h3>
            <span className="text-[10px] font-mono text-slate-500">({posts.length})</span>
          </div>
          <button onClick={() => void refresh()} disabled={loading} className="p-1 text-slate-500 hover:text-indigo-400 transition-colors disabled:opacity-30">
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
        <div className="overflow-y-auto max-h-[400px]">
          {posts.length === 0 ? (
            <div className="flex flex-col items-center gap-2 text-slate-600 py-8">
              <Send className="w-6 h-6 opacity-30" />
              <span className="text-xs font-mono">No publishing posts yet</span>
              <span className="text-[10px] text-slate-700">Create a post from a completed clip to publish</span>
            </div>
          ) : (
            posts.map((post) => (
              <div key={post.post_id} className="flex items-start gap-3 px-4 py-3 border-b border-slate-800/60 hover:bg-slate-800/30 transition-colors">
                <div className={`shrink-0 mt-0.5 ${statusColor(post.status)}`}>
                  {statusIcon(post.status)}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-mono text-slate-200 capitalize">{post.platform}</span>
                    <span className={`text-[10px] font-mono font-semibold ${statusColor(post.status)}`}>
                      {post.status.toUpperCase()}
                    </span>
                  </div>
                  <div className="text-[10px] text-slate-500 font-mono truncate mt-0.5">
                    {post.post_id} · job:{post.render_job_id}
                  </div>
                  {post.caption && <div className="text-[10px] text-slate-400 truncate mt-0.5">{post.caption}</div>}
                  {post.post_url && (
                    <a href={post.post_url} target="_blank" rel="noopener noreferrer" className="text-[10px] text-indigo-400 hover:text-indigo-300 truncate block mt-0.5">
                      {post.post_url}
                    </a>
                  )}
                  {post.error_message && (
                    <div className="text-[10px] text-rose-400 truncate mt-0.5">{post.error_message}</div>
                  )}
                  {post.compliance_verdict === 'blocked' && post.compliance_reasons.length > 0 && (
                    <div className="text-[10px] text-amber-400 mt-0.5">
                      Blocked: {post.compliance_reasons.join('; ')}
                    </div>
                  )}
                </div>
                <div className="flex items-center gap-1 shrink-0">
                  {post.status === 'failed' && (
                    <button
                      onClick={() => handleRetry(post.post_id)}
                      disabled={actionLoading === `retry-${post.post_id}`}
                      className="p-1 text-slate-500 hover:text-indigo-400 transition-colors disabled:opacity-30"
                      title="Retry"
                    >
                      {actionLoading === `retry-${post.post_id}` ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RotateCcw className="w-3.5 h-3.5" />}
                    </button>
                  )}
                  {['draft', 'ready', 'queued'].includes(post.status) && (
                    <button
                      onClick={() => handleCancel(post.post_id)}
                      disabled={actionLoading === `cancel-${post.post_id}`}
                      className="p-1 text-slate-500 hover:text-rose-400 transition-colors disabled:opacity-30"
                      title="Cancel"
                    >
                      <X className="w-3.5 h-3.5" />
                    </button>
                  )}
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
};
