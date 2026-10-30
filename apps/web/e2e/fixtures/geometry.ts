import type { Page } from '@playwright/test';

export type RectSnapshot = { x: number; y: number; width: number; height: number; right: number; bottom: number };
export type GeometryFinding = {
  kind: string;
  scenario: string;
  selectors: string[];
  rects: RectSnapshot[];
  reason: string;
};
export type GeometryReport = {
  viewport: { width: number; height: number };
  findings: GeometryFinding[];
  scrollContainers: {
    selector: string;
    rect: RectSnapshot;
    scrollWidth: number;
    clientWidth: number;
    scrollHeight: number;
    clientHeight: number;
  }[];
};

/**
 * Geometry checks used by the UI audit. Visibility and reachability are intentionally
 * separate: a visible control below the fold is valid when its scroll owner can reveal it;
 * a control clipped by an overflow boundary or hidden by an ARIA/inert ancestor is not an
 * interactive surface and must not create geometry noise.
 */
export async function inspectGeometry(
  page: Page,
  contract: { allowDocumentYScroll: boolean; allowDocumentXScroll: boolean; scenario?: string },
): Promise<GeometryReport> {
  return page.evaluate(async (routeContract) => {
    const EPSILON = 2;
    const viewport = { width: window.innerWidth, height: window.innerHeight };
    const findings: GeometryFinding[] = [];
    const scenario = routeContract.scenario ?? 'base';
    const selector = (element: Element): string => {
      const id = element.id ? `#${CSS.escape(element.id)}` : '';
      const classes = Array.from(element.classList)
        .slice(0, 2)
        .map((name) => `.${CSS.escape(name)}`)
        .join('');
      return `${element.tagName.toLowerCase()}${id}${classes}`;
    };
    const box = (element: Element): RectSnapshot => {
      const rect = element.getBoundingClientRect();
      return { x: rect.x, y: rect.y, width: rect.width, height: rect.height, right: rect.right, bottom: rect.bottom };
    };
    const hasHiddenAncestor = (element: Element): boolean => {
      let current: Element | null = element;
      while (current) {
        const style = getComputedStyle(current);
        if (
          current.hasAttribute('hidden') ||
          current.getAttribute('aria-hidden') === 'true' ||
          current.hasAttribute('inert') ||
          style.display === 'none' ||
          style.visibility === 'hidden' ||
          Number(style.opacity) === 0
        ) {
          return true;
        }
        if (current.matches('[role="menu"], .nav-menu, [data-geometry-menu]')) {
          const trigger = current.parentElement?.querySelector('[aria-expanded]');
          if (trigger?.getAttribute('aria-expanded') === 'false') return true;
        }
        current = current.parentElement;
      }
      return false;
    };
    const clipsOverflow = (style: CSSStyleDeclaration): boolean =>
      [style.overflowX, style.overflowY].some((value) => ['hidden', 'auto', 'scroll', 'clip'].includes(value));
    const visibleRect = (element: Element): RectSnapshot | null => {
      const rect = element.getBoundingClientRect();
      let left = Math.max(0, rect.left);
      let top = Math.max(0, rect.top);
      let right = Math.min(viewport.width, rect.right);
      let bottom = Math.min(viewport.height, rect.bottom);
      let current: Element | null = element;
      const fixedElement = getComputedStyle(element).position === 'fixed';
      while (current) {
        const style = getComputedStyle(current);
        if (clipsOverflow(style)) {
          const clip = current.getBoundingClientRect();
          left = Math.max(left, clip.left);
          top = Math.max(top, clip.top);
          right = Math.min(right, clip.right);
          bottom = Math.min(bottom, clip.bottom);
        }
        // A fixed surface is not clipped by ordinary ancestors above its
        // containing block. Include that fixed ancestor's own clip, then stop.
        if (fixedElement || (current !== element && style.position === 'fixed')) break;
        current = current.parentElement;
      }
      if ((right - left) * (bottom - top) <= EPSILON * EPSILON) return null;
      return { x: left, y: top, width: right - left, height: bottom - top, right, bottom };
    };
    const visible = (element: Element): boolean => {
      const rect = visibleRect(element);
      return !hasHiddenAncestor(element) && Boolean(rect);
    };
    const isOverlay = (element: Element): boolean =>
      Boolean(
        element.closest(
          '[role="dialog"], [aria-modal="true"], .command-palette-backdrop, .popover, [data-geometry-overlay]',
        ),
      );
    const nearestScrollContext = (element: Element): Element | null => {
      let current: Element | null = element.parentElement;
      while (current) {
        const style = getComputedStyle(current);
        if ([style.overflowX, style.overflowY].some((value) => ['auto', 'scroll', 'hidden', 'clip'].includes(value)))
          return current;
        current = current.parentElement;
      }
      return null;
    };
    const canScrollX = (element: Element): boolean => {
      const style = getComputedStyle(element);
      return (
        (style.overflowX === 'auto' || style.overflowX === 'scroll') &&
        element.scrollWidth > element.clientWidth + EPSILON
      );
    };
    const canScrollY = (element: Element): boolean => {
      const style = getComputedStyle(element);
      return (
        (style.overflowY === 'auto' || style.overflowY === 'scroll') &&
        element.scrollHeight > element.clientHeight + EPSILON
      );
    };
    const localXScrollOwner = (element: Element): Element | null => {
      let current: Element | null = element.parentElement;
      while (current) {
        if (canScrollX(current)) {
          const rect = current.getBoundingClientRect();
          return rect.left >= -EPSILON && rect.right <= viewport.width + EPSILON ? current : null;
        }
        current = current.parentElement;
      }
      return null;
    };
    const interactive = Array.from(
      document.querySelectorAll('button, a[href], input, select, textarea, [role="button"]'),
    ).filter((element) => visible(element) && !(element as HTMLButtonElement).disabled);
    const significant = Array.from(
      document.querySelectorAll(
        'html, body, main, header, nav, aside, [class*="shell"], [class*="layout"], [class*="content"], [class*="panel"], [class*="table"], [class*="graph"], [class*="terminal"], [class*="chat"]',
      ),
    ).filter(visible);
    const allScrollables = () =>
      [...new Set([document.documentElement, document.body, ...significant])].filter(
        (element) => canScrollX(element) || canScrollY(element),
      );
    const scrollContainers = allScrollables().map((element) => ({
      selector: selector(element),
      rect: box(element),
      scrollWidth: element.scrollWidth,
      clientWidth: element.clientWidth,
      scrollHeight: element.scrollHeight,
      clientHeight: element.clientHeight,
    }));
    // Read every rectangle once. A live collection of independent reads can mix
    // layout generations when React/font/layout work lands between reads.
    const rects = new Map<Element, RectSnapshot>();
    const snapshot = (element: Element): RectSnapshot => {
      const existing = rects.get(element);
      if (existing) return existing;
      const value = box(element);
      rects.set(element, value);
      return value;
    };
    const report = (kind: string, elements: Element[], reason: string) =>
      findings.push({ kind, scenario, selectors: elements.map(selector), rects: elements.map(snapshot), reason });
    const isIntentionalLocalScroll = (element: Element): boolean =>
      element.matches(
        '[data-geometry-scroll-ok], .ui-table-wrap, .table-wrap, .message-scroll, .chats-sidebar, .workspace-center, .session-terminal-extra, .event-log, .file-tree',
      );
    const isRelatedControl = (a: Element, b: Element): boolean => {
      if (a.contains(b) || b.contains(a)) return true;
      const label = a.tagName === 'LABEL' ? a : b.tagName === 'LABEL' ? b : (a.closest('label') ?? b.closest('label'));
      if (!label) return false;
      const control = (label as HTMLLabelElement).control;
      return Boolean(control && (control === a || control === b || label.contains(a) || label.contains(b)));
    };
    const scrollOwner = (element: Element, axis: 'x' | 'y'): Element | null => {
      let current: Element | null = element.parentElement;
      while (current) {
        if (axis === 'x' ? canScrollX(current) : canScrollY(current)) return current;
        current = current.parentElement;
      }
      if (axis === 'x')
        return document.documentElement.scrollWidth > document.documentElement.clientWidth + EPSILON
          ? document.documentElement
          : null;
      return document.documentElement.scrollHeight > document.documentElement.clientHeight + EPSILON
        ? document.documentElement
        : null;
    };
    const canReach = (element: Element, axis: 'x' | 'y'): boolean => {
      return scrollOwner(element, axis) !== null;
    };

    for (const element of [...new Set([document.documentElement, document.body, ...significant])]) {
      if (element.scrollWidth <= element.clientWidth + EPSILON) continue;
      const style = getComputedStyle(element);
      if (
        element === document.documentElement ||
        element === document.body ||
        (!canScrollX(element) && !localXScrollOwner(element))
      ) {
        report(
          'horizontal-overflow',
          [element],
          `scrollWidth ${element.scrollWidth}px exceeds clientWidth ${element.clientWidth}px (overflow-x: ${style.overflowX})`,
        );
      }
    }
    for (const element of significant) {
      const rect = element.getBoundingClientRect();
      if (rect.left < -EPSILON || rect.right > viewport.width + EPSILON) {
        const style = getComputedStyle(element);
        if (
          style.position !== 'fixed' &&
          !canScrollX(element) &&
          !localXScrollOwner(element) &&
          !element.closest('[data-geometry-horizontal-scroll]')
        ) {
          report(
            'layout-rect-overflow',
            [element],
            `visible layout rect is outside viewport (${rect.left.toFixed(1)}..${rect.right.toFixed(1)})`,
          );
        }
      }
    }
    for (const element of interactive) {
      const rect = element.getBoundingClientRect();
      const horizontalOutside = rect.left < -EPSILON || rect.right > viewport.width + EPSILON;
      const verticalOutside = rect.top < -EPSILON || rect.bottom > viewport.height + EPSILON;
      const style = getComputedStyle(element);
      if (
        horizontalOutside &&
        style.position !== 'fixed' &&
        !element.closest('[data-geometry-horizontal-scroll]') &&
        !canReach(element, 'x')
      ) {
        report(
          'interactive-out-of-viewport',
          [element],
          'visible interactive control is horizontally outside the viewport without a scroll owner that can reveal it',
        );
      } else if (
        verticalOutside &&
        style.position !== 'fixed' &&
        !element.closest('[role="dialog"], .command-palette-backdrop') &&
        !canReach(element, 'y')
      ) {
        report(
          'interactive-out-of-viewport',
          [element],
          'visible interactive control has no scroll owner that can reveal it',
        );
      }
    }
    for (let i = 0; i < interactive.length; i += 1) {
      for (let j = i + 1; j < interactive.length; j += 1) {
        const a = interactive[i];
        const b = interactive[j];
        if (isRelatedControl(a, b) || isOverlay(a) !== isOverlay(b)) continue;
        const ar = visibleRect(a);
        const br = visibleRect(b);
        if (!ar || !br) continue;
        const overlap =
          Math.max(0, Math.min(ar.right, br.right) - Math.max(ar.x, br.x)) *
          Math.max(0, Math.min(ar.bottom, br.bottom) - Math.max(ar.y, br.y));
        // Sticky/fixed elements have their own occlusion rule below. At a
        // particular scroll offset their rectangles may overlap content that
        // remains reachable after scrolling, which is not an interactive overlap.
        const positioned = [a, b].some((element) => ['fixed', 'sticky'].includes(getComputedStyle(element).position));
        if (overlap > EPSILON * EPSILON && !positioned)
          report('interactive-overlap', [a, b], `independent interactive elements overlap by ${overlap.toFixed(1)}px²`);
      }
    }
    const originalWindowScroll = { left: window.scrollX, top: window.scrollY };
    const restoreScroll = () => {
      window.scrollTo(originalWindowScroll.left, originalWindowScroll.top);
      for (const element of Array.from(document.querySelectorAll<HTMLElement>('*'))) {
        const state = scrollState.get(element);
        if (state) {
          element.scrollLeft = state.left;
          element.scrollTop = state.top;
        }
      }
    };
    const frame = () =>
      new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
    const scrollState = new Map<Element, { left: number; top: number }>();
    scrollState.set(document.documentElement, { left: window.scrollX, top: window.scrollY });
    for (const element of Array.from(document.querySelectorAll<HTMLElement>('*'))) {
      if (element.scrollWidth > element.clientWidth || element.scrollHeight > element.clientHeight) {
        scrollState.set(element, { left: element.scrollLeft, top: element.scrollTop });
      }
    }
    const remainsOccludedAfterScroll = async (overlay: Element, target: Element): Promise<boolean> => {
      target.scrollIntoView({ block: 'center', inline: 'nearest', behavior: 'auto' });
      await frame();
      const overlayRect = overlay.getBoundingClientRect();
      const targetRect = target.getBoundingClientRect();
      const area =
        Math.max(0, Math.min(overlayRect.right, targetRect.right) - Math.max(overlayRect.left, targetRect.left)) *
        Math.max(0, Math.min(overlayRect.bottom, targetRect.bottom) - Math.max(overlayRect.top, targetRect.top));
      restoreScroll();
      return area > EPSILON * EPSILON;
    };
    const positioned = Array.from(document.querySelectorAll('body *')).filter(
      (element) => visible(element) && ['fixed', 'sticky'].includes(getComputedStyle(element).position),
    );
    for (const overlay of positioned) {
      if (isOverlay(overlay)) continue;
      const or = snapshot(overlay);
      for (const element of Array.from(document.querySelectorAll('main, main *')).filter(visible)) {
        if (element === overlay || overlay.contains(element) || element.contains(overlay)) continue;
        const er = snapshot(element);
        const overlap =
          Math.max(0, Math.min(or.right, er.right) - Math.max(or.x, er.x)) *
          Math.max(0, Math.min(or.bottom, er.bottom) - Math.max(or.y, er.y));
        const overlayContext = nearestScrollContext(overlay);
        const targetContext = nearestScrollContext(element);
        // A sticky table header is constrained by its table wrapper. It can share
        // a viewport rectangle with a heading in a sibling scroll context without
        // ever painting over that heading.
        if (overlayContext && overlayContext !== targetContext && !overlayContext.contains(element)) continue;
        if (
          overlap > EPSILON * EPSILON &&
          (element.matches('button, a[href], input, select, textarea, [role="button"]') ||
            element.matches('h1, h2, h3')) &&
          (await remainsOccludedAfterScroll(overlay, element))
        ) {
          report(
            'sticky-fixed-overlap',
            [overlay, element],
            'sticky/fixed content still covers the target after it is scrolled to a safe position',
          );
        }
      }
    }
    for (const element of interactive) {
      const rect = visibleRect(element);
      if (!rect) continue;
      const hit = document.elementFromPoint(rect.x + rect.width / 2, rect.y + rect.height / 2);
      const hitSurface = hit?.closest(
        'button, a[href], input, select, textarea, [role="button"], [role="link"], [onclick], [tabindex]:not([tabindex="-1"])',
      );
      if (hit && hit !== element && !element.contains(hit) && !isRelatedControl(element, hit) && hitSurface) {
        report('interactive-hit-test', [element, hit], 'center point is intercepted by an unrelated element');
      }
    }
    if (!routeContract.allowDocumentXScroll && document.documentElement.scrollWidth > viewport.width + EPSILON)
      report(
        'document-horizontal-scroll',
        [document.documentElement],
        'route contract disallows document horizontal scrolling',
      );
    if (!routeContract.allowDocumentYScroll && document.documentElement.scrollHeight > viewport.height + EPSILON)
      report(
        'unexpected-document-scroll',
        [document.documentElement],
        'one-screen route contract disallows document vertical scrolling',
      );
    const scrollable = allScrollables();
    for (const outer of scrollable) {
      for (const inner of scrollable) {
        if (outer === inner || !outer.contains(inner) || isIntentionalLocalScroll(inner)) continue;
        report(
          'nested-scroll-container',
          [outer, inner],
          'nested non-local scroll containers compete for scroll ownership',
        );
      }
    }
    return { viewport, findings, scrollContainers };
  }, contract);
}
