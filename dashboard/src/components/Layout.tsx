import { useState, useEffect } from 'react';
import {
  LayoutDashboard,
  Radio,
  Building2,
  Activity,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react';
import { cn } from '../utils';
import type { Page } from '../types';

interface LayoutProps {
  currentPage: Page;
  onNavigate: (page: Page) => void;
  children: React.ReactNode;
}

const NAV_ITEMS: { page: Page; label: string; icon: typeof LayoutDashboard }[] = [
  { page: 'overview', label: 'Overview', icon: LayoutDashboard },
  { page: 'signals', label: 'Signals', icon: Radio },
  { page: 'competitors', label: 'Competitors', icon: Building2 },
  { page: 'status', label: 'Status', icon: Activity },
];

export default function Layout({ currentPage, onNavigate, children }: LayoutProps) {
  const [collapsed, setCollapsed] = useState(false);
  const [clock, setClock] = useState('');

  useEffect(() => {
    const tick = () => setClock(new Date().toLocaleTimeString('cs-CZ'));
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="min-h-screen bg-[#f4f4f5] text-slate-600 font-sans selection:bg-yellow-400/30">
      <a href="#main-content" className="skip-link">Skip to main content</a>
      {/* Header */}
      <header className="bg-white border-b border-slate-200 px-6 py-4 flex items-center justify-between shadow-sm sticky top-0 z-50">
        <div className="flex items-center gap-4">
          <div
            role="img"
            aria-label="Raiffeisenbank logo"
            className="w-10 h-10 bg-[#fee600] rounded flex items-center justify-center text-black font-black text-xl shadow-sm"
          >
            RB
          </div>
          <div>
            <h1 className="text-slate-900 font-bold text-lg leading-tight uppercase tracking-tight">
              Market Intelligence Monitor
            </h1>
            <p className="text-[10px] font-bold text-slate-400 uppercase tracking-widest">
              Czech Banking Sector &bull; Competitive Intelligence Platform
            </p>
          </div>
        </div>
        <div className="flex items-center gap-6">
          <div className="text-right">
            <div className="text-slate-900 font-mono text-sm font-bold">{clock}</div>
            <div className="text-[10px] text-slate-400 uppercase tracking-wider font-bold">
              11 targets &bull; 3 sources
            </div>
          </div>
          <div className="w-2.5 h-2.5 bg-green-500 rounded-full shadow-[0_0_8px_rgba(34,197,94,0.4)]" />
        </div>
      </header>

      <div className="flex relative">
        {/* Sidebar */}
        <aside
          aria-label="Primary navigation"
          className={cn(
            'bg-white border-r border-slate-200 h-[calc(100vh-73px)] sticky top-[73px] overflow-y-auto transition-all duration-300 z-40 flex flex-col',
            collapsed ? 'w-16' : 'w-56'
          )}
        >
          <nav className="flex-1 py-4">
            {NAV_ITEMS.map(({ page, label, icon: Icon }) => (
              <button
                key={page}
                type="button"
                onClick={() => onNavigate(page)}
                aria-current={currentPage === page ? 'page' : undefined}
                aria-label={label}
                className={cn(
                  'w-full flex items-center gap-3 px-5 py-3.5 text-[10px] font-black uppercase tracking-widest transition-all',
                  currentPage === page
                    ? 'bg-yellow-50 text-slate-900 border-r-2 border-[#fee600]'
                    : 'text-slate-400 hover:text-slate-900 hover:bg-slate-50'
                )}
                title={label}
              >
                <Icon size={16} className={currentPage === page ? 'text-[#e6cf00]' : ''} aria-hidden="true" />
                {!collapsed && <span>{label}</span>}
              </button>
            ))}
          </nav>
          <button
            type="button"
            onClick={() => setCollapsed(!collapsed)}
            aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            aria-expanded={!collapsed}
            className="p-4 text-slate-300 hover:text-slate-600 transition-colors border-t border-slate-100"
          >
            {collapsed ? <ChevronRight size={14} aria-hidden="true" /> : <ChevronLeft size={14} aria-hidden="true" />}
          </button>
        </aside>

        {/* Main content */}
        <main id="main-content" className="flex-1 p-6 min-w-0">{children}</main>
      </div>

      {/* Footer */}
      <footer className="bg-white border-t border-slate-200 px-6 py-3 flex items-center justify-between text-[9px] font-black uppercase tracking-[0.2em] text-slate-400 sticky bottom-0 z-50">
        <div className="flex gap-8">
          <span className="flex items-center gap-2">
            <div className="w-1.5 h-1.5 rounded-full bg-green-500" /> System Active
          </span>
          <span>SQLite Backend</span>
        </div>
        <span className="text-slate-300">&copy; 2026 RB Market Intelligence</span>
      </footer>
    </div>
  );
}
