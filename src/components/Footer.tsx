import React, { useEffect, useState } from 'react';

export const Footer: React.FC = () => {
  const [time, setTime] = useState<string>('');

  useEffect(() => {
    const updateTime = () => {
      const now = new Date();
      setTime(now.toISOString().replace('T', ' ').substring(0, 19) + ' UTC');
    };
    updateTime();
    const timer = setInterval(updateTime, 1000);
    return () => clearInterval(timer);
  }, []);

  return (
    <footer className="h-8 bg-[#020617] border-t border-slate-800 flex items-center px-6 justify-between shrink-0 select-none text-[9px] text-slate-500 font-mono tracking-wider">
      <div className="flex items-center gap-4">
        <span>SESSION_ID: 9XF-7K2-PROD-ORACLE</span>
        <span className="hidden md:inline text-slate-700">|</span>
        <span className="hidden md:inline text-slate-400">ENGINE: ZERO-LLM-V13</span>
      </div>

      <div className="flex items-center gap-4">
        <span className="hidden sm:inline text-slate-500">{time}</span>
        <span className="hidden sm:inline text-slate-700">|</span>
        <span className="text-slate-400">SOURCE_REPOSITORY_EXTRACTED: SUCCESS [412 FILES]</span>
      </div>
    </footer>
  );
};
