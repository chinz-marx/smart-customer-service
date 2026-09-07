// 仅开发环境记录生命周期和 HMR 事件，不记录对话内容或用户参数。
if (import.meta.env.DEV) {
  const key = 'customer-service:reload-events';
  type Entry = { time: string; event: string };
  let entries: Entry[] = [];
  try {
    const stored: unknown = JSON.parse(sessionStorage.getItem(key) || '[]');
    if (Array.isArray(stored)) {
      entries = stored.filter((item): item is Entry =>
        item !== null && typeof item === 'object'
        && typeof item.time === 'string' && typeof item.event === 'string',
      ).slice(-20);
    }
  } catch { /* 存储不可用时不影响聊天。 */ }

  const record = (event: string) => {
    entries.push({ time: new Date().toISOString(), event });
    entries = entries.slice(-20);
    try { sessionStorage.setItem(key, JSON.stringify(entries)); } catch { /* 可选诊断。 */ }
    console.debug('[page-lifecycle]', event);
  };
  console.debug('[page-lifecycle] previous', JSON.stringify(entries));
  const navigation = performance.getEntriesByType('navigation')[0] as PerformanceNavigationTiming | undefined;
  record(`load:${navigation?.type ?? 'unknown'}`);
  const onPageHide = (event: PageTransitionEvent) => record(`pagehide:cached=${event.persisted}`);
  const onHashChange = () => record('hashchange');
  window.addEventListener('pagehide', onPageHide);
  window.addEventListener('hashchange', onHashChange);
  import.meta.hot?.on('vite:beforeFullReload', () => record('hmr:full-reload'));
  import.meta.hot?.on('vite:ws:disconnect', () => record('hmr:disconnect'));
  import.meta.hot?.on('vite:ws:connect', () => record('hmr:connect'));
  import.meta.hot?.on('vite:beforeUpdate', () => record('hmr:update'));
  import.meta.hot?.dispose(() => {
    window.removeEventListener('pagehide', onPageHide);
    window.removeEventListener('hashchange', onHashChange);
  });
}

export {};
