// Keep Furo's native controls; add localized names and keyboard access to scrolling regions.
(() => {
  const chinese = document.documentElement.lang.startsWith('zh');
  // Old guide fragments follow the canonical task links after pages are split.
  const followGuideFragment = () => {
    if (!location.hash) return false;
    const fragment = location.hash.slice(1);
    const destination = [...document.querySelectorAll('.guide-links a[href], .guide-redirects a[href]')].find(link =>
      (link.hash === location.hash || link.dataset.legacyFragment === fragment) && link.pathname !== location.pathname);
    if (!destination) return false;
    location.replace(destination.href);
    return true;
  };
  if (followGuideFragment()) return;
  window.addEventListener('hashchange', followGuideFragment);

  if (chinese) {
    document.querySelectorAll('.toc-title').forEach(element => {
      element.textContent = '本页目录';
    });
    for (const [selector, label] of [
      ['.related-pages .prev-page .context span', '上一页'],
      ['.related-pages .next-page .context span', '下一页'],
    ]) document.querySelectorAll(selector).forEach(element => { element.textContent = label; });

    const labels = new Map([
      ['Toggle site navigation sidebar', '打开或关闭站点导航'],
      ['Toggle table of contents sidebar', '打开或关闭本页目录'],
    ]);
    const navigationPrefix = 'Toggle navigation of ';
    document.querySelectorAll('[aria-label]').forEach(element => {
      const label = element.getAttribute('aria-label');
      if (labels.has(label)) element.setAttribute('aria-label', labels.get(label));
      else if (label.startsWith(navigationPrefix)) {
        element.setAttribute('aria-label', '展开或收起：' + label.slice(navigationPrefix.length));
      }
    });
  }

  const updateThemeNames = () => {
    const theme = document.body.dataset.theme || 'auto';
    const names = chinese
      ? { light: '浅色', dark: '深色', auto: '跟随系统' }
      : { light: 'Light', dark: 'Dark', auto: 'System' };
    const label = chinese
      ? `切换主题（当前：${names[theme] || names.auto}）`
      : `Switch color theme (current: ${names[theme] || names.auto})`;
    document.querySelectorAll('.theme-toggle').forEach(button => {
      button.setAttribute('aria-label', label);
      button.title = label;
    });
  };
  updateThemeNames();
  new MutationObserver(updateThemeNames).observe(document.body, {
    attributes: true, attributeFilter: ['data-theme'],
  });

  // Furo's mobile drawer labels need keyboard activation as well as pointer input.
  for (const [inputId, controlSelector, drawerSelector, name] of [
    ['__navigation', '.nav-overlay-icon', '.sidebar-drawer', chinese ? '站点导航' : 'Site navigation'],
    ['__toc', '.toc-overlay-icon', '.toc-drawer', chinese ? '本页目录' : 'On this page'],
  ]) {
    const input = document.getElementById(inputId);
    const drawer = document.querySelector(drawerSelector);
    if (!input || !drawer) continue;
    drawer.id ||= 'docs-' + inputId;
    document.querySelectorAll(controlSelector).forEach(control => {
      control.tabIndex = 0;
      control.setAttribute('role', 'button');
      control.setAttribute('aria-label', name);
      control.setAttribute('aria-controls', drawer.id);
      const update = () => control.setAttribute('aria-expanded', String(input.checked));
      update();
      input.addEventListener('change', update);
      control.addEventListener('keydown', event => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          input.click();
        }
      });
    });
  }

  // Some Sphinx versions render navigation captions as headings without a level.
  document.querySelectorAll('.caption[role="heading"]:not([aria-level])').forEach(element => {
    element.setAttribute('aria-level', element.closest('.sidebar-tree') ? '2' : '3');
  });

  const regions = [...document.querySelectorAll('.content .table-wrapper, .content .highlight pre')];
  const updateRegion = element => {
    if (element.scrollWidth > element.clientWidth + 1) {
      element.tabIndex = 0;
      element.setAttribute('role', 'region');
      const table = element.classList.contains('table-wrapper');
      element.setAttribute('aria-label', table
        ? (chinese ? '可横向滚动的表格' : 'Scrollable table')
        : (chinese ? '可横向滚动的代码' : 'Scrollable code'));
    } else {
      for (const name of ['tabindex', 'role', 'aria-label']) element.removeAttribute(name);
    }
  };
  regions.forEach(updateRegion);
  if (typeof ResizeObserver !== 'undefined') {
    const observer = new ResizeObserver(entries => entries.forEach(entry => updateRegion(entry.target)));
    regions.forEach(element => observer.observe(element));
  } else {
    window.addEventListener('resize', () => regions.forEach(updateRegion));
  }
})();
