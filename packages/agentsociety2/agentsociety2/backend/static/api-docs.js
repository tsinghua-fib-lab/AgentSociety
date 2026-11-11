(() => {
  const root = document.documentElement;
  const storageKey = 'agentsociety-api-theme';
  const media = matchMedia('(prefers-color-scheme: dark)');
  let chosen;
  try { chosen = localStorage.getItem(storageKey); } catch { /* Private storage can be unavailable. */ }
  const applyTheme = () => {
    root.dataset.theme = chosen === 'dark' || chosen === 'light' ? chosen : media.matches ? 'dark' : 'light';
    const button = document.getElementById('api-theme');
    if (button) {
      const next = root.dataset.theme === 'dark' ? '浅色' : '深色';
      button.textContent = next;
      button.setAttribute('aria-label', `切换至${next}主题`);
      button.title = `切换至${next}主题`;
    }
  };
  applyTheme();
  media.addEventListener('change', applyTheme);

  const ready = () => {
    const themeButton = document.getElementById('api-theme');
    themeButton?.addEventListener('click', () => {
      chosen = root.dataset.theme === 'dark' ? 'light' : 'dark';
      try { localStorage.setItem(storageKey, chosen); } catch { /* Theme still works without persistence. */ }
      applyTheme();
    });
    applyTheme();
    const container = document.getElementById('swagger-ui');
    if (!container) return;

    const enhance = () => {
      const description = container.querySelector('.info > .description');
      const filter = container.querySelector('.operation-filter-input');
      if (!description || !filter) return false;
      if (!description.closest('details')) {
        const details = document.createElement('details');
        details.className = 'api-instructions';
        const summary = document.createElement('summary');
        summary.textContent = '使用说明与工作区约定';
        description.before(details);
        details.append(summary, description);
      }
      filter.placeholder = '筛选分组或路径，例如 modules、replay';
      filter.setAttribute('aria-label', '筛选接口分组或路径');
      return true;
    };
    if (!enhance()) {
      const observer = new MutationObserver(() => { if (enhance()) observer.disconnect(); });
      observer.observe(container, { childList: true, subtree: true });
    }

    // Swagger renders parameters and responses lazily as operations are expanded.
    const labelControls = () => {
      container.querySelectorAll('.servers select, tr[data-param-name] select').forEach(select => {
        if (select.hasAttribute('aria-label') || select.hasAttribute('aria-labelledby')) return;
        const name = select.closest('tr')?.dataset.paramName;
        select.setAttribute('aria-label', name ? `参数 ${name}` : '后端服务地址');
      });
      container.querySelectorAll('.curl, pre.microlight').forEach(block => {
        if (block.scrollWidth > block.clientWidth + 1 && !block.hasAttribute('tabindex')) {
          block.tabIndex = 0;
          block.setAttribute('role', 'region');
          block.setAttribute('aria-label', block.classList.contains('curl') ? '请求命令' : '代码内容');
        }
      });
    };
    labelControls();
    new MutationObserver(labelControls).observe(container, { childList: true, subtree: true });
    addEventListener('resize', labelControls);

    const links = [...document.querySelectorAll('.api-group-link')];
    const markActive = tag => {
      links.forEach(link => {
        if (link.dataset.apiTag === tag) link.setAttribute('aria-current', 'location');
        else link.removeAttribute('aria-current');
      });
    };
    const syncHash = () => {
      const tag = location.hash.split('/')[1];
      if (tag) {
        try { markActive(decodeURIComponent(tag)); } catch { links.forEach(link => link.removeAttribute('aria-current')); }
      } else links.forEach(link => link.removeAttribute('aria-current'));
    };
    syncHash();
    addEventListener('hashchange', syncHash);
    links.forEach(link => link.addEventListener('click', event => {
      event.preventDefault();
      const tag = link.dataset.apiTag;
      const filter = container.querySelector('.operation-filter-input');
      if (filter?.value) {
        Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(filter, '');
        filter.dispatchEvent(new Event('input', { bubbles: true }));
      }
      let attempts = 0;
      const reveal = () => {
        const heading = [...container.querySelectorAll('.opblock-tag')].find(element => element.dataset.tag === tag);
        if (!heading) {
          if (++attempts < 60) requestAnimationFrame(reveal);
          return;
        }
        if (heading.dataset.isOpen !== 'true') heading.click();
        history.replaceState(null, '', link.hash);
        markActive(tag);
        requestAnimationFrame(() => {
          heading.querySelector('a')?.focus({ preventScroll: true });
          heading.scrollIntoView({ block: 'start', behavior: 'instant' });
        });
      };
      reveal();
    }));
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', ready, { once: true });
  else ready();
})();
