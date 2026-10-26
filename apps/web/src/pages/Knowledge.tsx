import { lazy, Suspense, useCallback, useEffect, useMemo, useState } from 'react';
import { api } from '../api/client';
import type { KnowledgeDocument, KnowledgeDocumentList } from '../api/types-knowledge';
import type { KnowledgeGraphResponse, SearchResponse } from '../api/types';
import { errorText, useApi } from '../api/useApi';
import { EmptyState } from '../components/EmptyState';
import { ErrorBanner } from '../components/ErrorBanner';
import { Loading } from '../components/Loading';
import { MarkdownView } from '../components/MarkdownView';
import { SplitPane } from '../components/ui';
import { t } from '../i18n';

const KnowledgeGraph = lazy(() => import('../components/KnowledgeGraph'));

const PAGE_SIZE = 50;
const escapeRegExp = (value: string) => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
const markQuery = (text: string, query: string) => {
  const parts = query.trim() ? text.split(new RegExp(`(${escapeRegExp(query.trim())})`, 'ig')) : [text];
  return parts.map((part, index) =>
    part.toLowerCase() === query.trim().toLowerCase() ? <mark key={index}>{part}</mark> : part,
  );
};

export function Knowledge(): JSX.Element {
  const [query, setQuery] = useState('');
  const [list, setList] = useState<KnowledgeDocumentList | null>(null);
  const [results, setResults] = useState<SearchResponse | null>(null);
  const [graph, setGraph] = useState<KnowledgeGraphResponse | null>(null);
  const [doc, setDoc] = useState<KnowledgeDocument | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [project, setProject] = useState('');
  const [type, setType] = useState('');
  const [sort, setSort] = useState<'updated' | 'title'>('updated');
  const [order, setOrder] = useState<'asc' | 'desc'>('desc');
  const [offset, setOffset] = useState(0);
  const [graphMode, setGraphMode] = useState<'overview' | 'projects' | 'focus'>(() => {
    try {
      const value = JSON.parse(localStorage.getItem('aihub.kg.ui.v1') ?? '{}').mode;
      return value === 'projects' || value === 'focus' ? value : 'overview';
    } catch {
      return 'overview';
    }
  });
  const [graphDepth, setGraphDepth] = useState<1 | 2>(() => {
    try {
      return JSON.parse(localStorage.getItem('aihub.kg.ui.v1') ?? '{}').depth === 2 ? 2 : 1;
    } catch {
      return 1;
    }
  });
  const [selectedEdgesOnly, setSelectedEdgesOnly] = useState(() => {
    try {
      return Boolean(JSON.parse(localStorage.getItem('aihub.kg.ui.v1') ?? '{}').selectedEdgesOnly);
    } catch {
      return false;
    }
  });
  const [legendOpen, setLegendOpen] = useState(false);
  const [graphSearch, setGraphSearch] = useState('');
  const [fitRequest, setFitRequest] = useState(0);
  const [resetRequest, setResetRequest] = useState(0);
  // The chosen view (list or graph) survives a reload.
  const [view, setViewState] = useState<'list' | 'graph'>(() => {
    try {
      return localStorage.getItem('aihub.knowledge.view') === 'graph' ? 'graph' : 'list';
    } catch {
      return 'list';
    }
  });
  const setView = (next: 'list' | 'graph') => {
    setViewState(next);
    try {
      localStorage.setItem('aihub.knowledge.view', next);
    } catch {
      // storage is optional
    }
  };
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState('');

  const loadList = useCallback(async () => {
    setBusy(true);
    try {
      const params = new URLSearchParams({ sort, order, offset: String(offset), limit: String(PAGE_SIZE) });
      if (project) params.set('project_id', project);
      if (type) params.set('type', type);
      setList(await api<KnowledgeDocumentList>(`/knowledge/documents?${params}`));
      setError('');
    } catch (cause) {
      setError(errorText(cause, t('Список знаний недоступен')));
    } finally {
      setBusy(false);
    }
  }, [offset, order, project, sort, type]);

  useEffect(() => {
    void loadList();
  }, [loadList]);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      if (!query.trim()) {
        setResults(null);
        return;
      }
      setResults(null);
      void api<SearchResponse>(`/knowledge/search?q=${encodeURIComponent(query)}&limit=50`)
        .then(setResults)
        .catch((cause) => setError(errorText(cause, t('Поиск недоступен'))));
    }, 160);
    return () => window.clearTimeout(timer);
  }, [query]);
  useEffect(() => {
    if (view !== 'graph' || graph) return;
    void api<KnowledgeGraphResponse>('/knowledge/graph')
      .then(setGraph)
      .catch((cause) => setError(errorText(cause, t('Граф недоступен'))));
  }, [graph, view]);
  useEffect(() => {
    localStorage.setItem('aihub.kg.ui.v1', JSON.stringify({ mode: graphMode, depth: graphDepth, selectedEdgesOnly }));
  }, [graphDepth, graphMode, selectedEdgesOnly]);

  const open = useCallback(async (id: string) => {
    setSelectedId(id);
    try {
      setDoc(await api<KnowledgeDocument>(`/knowledge/documents/${encodeURIComponent(id)}`));
    } catch (cause) {
      setError(errorText(cause, t('Не удалось открыть документ')));
    }
  }, []);
  // Desktop: open the newest note right away instead of an empty «choose a note» panel.
  useEffect(() => {
    const first = list?.items?.[0];
    if (!selectedId && first && view === 'list' && window.matchMedia('(min-width: 901px)').matches) void open(first.id);
  }, [list, open, selectedId, view]);
  const shownResults = useMemo(() => results?.hits ?? [], [results]);
  const graphSuggestions = useMemo(() => {
    const needle = graphSearch.trim().toLowerCase();
    if (!graph || !needle) return [];
    return graph.nodes.filter((node) => node.title.toLowerCase().includes(needle)).slice(0, 8);
  }, [graph, graphSearch]);
  const visibleGraph = useMemo(() => {
    if (!graph) return null;
    return {
      nodes: graph.nodes.filter((node) => (!project || node.project_id === project) && (!type || node.type === type)),
      edges: graph.edges,
    };
  }, [graph, project, type]);
  const clear = () => {
    setQuery('');
    setOffset(0);
    void loadList();
  };
  const selectGraphNode = (id: string) => {
    setSelectedId(id);
    setGraphSearch('');
    void open(id);
  };
  const selectedConnections = useMemo(() => {
    if (!graph || !selectedId) return { incoming: [], outgoing: [] };
    const incoming = graph.edges.filter((edge) => edge.target === selectedId);
    const outgoing = graph.edges.filter((edge) => edge.source === selectedId);
    const title = new Map(graph.nodes.map((node) => [node.id, node.title]));
    return {
      incoming: incoming.map((edge) => ({ ...edge, title: title.get(edge.source) ?? edge.source })),
      outgoing: outgoing.map((edge) => ({ ...edge, title: title.get(edge.target) ?? edge.target })),
    };
  }, [graph, selectedId]);
  const vault = useApi<{ obsidian_vault?: string }>('/system/info').data?.obsidian_vault ?? '';
  const obsidianUrl =
    doc && vault
      ? `obsidian://open?vault=${encodeURIComponent(vault)}&file=${encodeURIComponent(doc.path.replace(/\.md$/i, ''))}`
      : '';
  const copyPath = () => {
    if (doc) void navigator.clipboard?.writeText(doc.path);
  };

  return (
    <div className={`knowledge-page ${view === 'graph' ? 'knowledge-graph-page' : ''}`}>
      <div className="page-heading">
        <div>
          <p className="eyebrow">{t('ПАМЯТЬ')}</p>
          <h1>{t('База знаний')}</h1>
          <p className="muted">{t('Документы и реальные связи Vault')}</p>
        </div>
        <div className="knowledge-view-toggle">
          <button className={view === 'list' ? 'active' : 'button-secondary'} onClick={() => setView('list')}>
            {t('Список')}
          </button>
          <button className={view === 'graph' ? 'active' : 'button-secondary'} onClick={() => setView('graph')}>
            {t('Граф')}
          </button>
        </div>
      </div>
      {error && <ErrorBanner message={error} />}
      {view === 'list' && (
        <div className="knowledge-toolbar panel">
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={t('Поиск по словам и смыслу…')}
            aria-label={t('Поиск по базе знаний')}
          />
          {query && (
            <button className="button-secondary" onClick={clear}>
              {t('Очистить')}
            </button>
          )}
          <input
            value={project}
            onChange={(event) => {
              setProject(event.target.value);
              setOffset(0);
            }}
            placeholder={t('Проект')}
            aria-label={t('Фильтр проекта')}
          />
          <input
            value={type}
            onChange={(event) => {
              setType(event.target.value);
              setOffset(0);
            }}
            placeholder={t('Тип документа/связи')}
            aria-label={t('Фильтр типа')}
          />
          <select
            value={sort}
            onChange={(event) => setSort(event.target.value as 'updated' | 'title')}
            aria-label={t('Сортировка')}
          >
            <option value="updated">{t('Обновлены')}</option>
            <option value="title">{t('Название')}</option>
          </select>
          <button
            className="button-secondary"
            onClick={() => setOrder(order === 'asc' ? 'desc' : 'asc')}
            aria-label={t('Изменить порядок сортировки')}
          >
            {order === 'asc' ? '↑' : '↓'}
          </button>
        </div>
      )}
      {view === 'list' ? (
        <section className="knowledge-list-layout" aria-label={t('Документы')}>
          <SplitPane
            className="knowledge-split"
            initial={520}
            min={360}
            max={900}
            storageKey="aihub.knowledge-list-split.v2"
          >
            <div className="knowledge-list-pane">
              {query && (
                <p className="muted">
                  {t('Результатов:')} {shownResults.length}
                </p>
              )}
              {busy || (Boolean(query) && results === null) ? (
                <Loading />
              ) : query ? (
                shownResults.length ? (
                  <ul className="hit-list">
                    {shownResults.map((hit) => (
                      <li
                        key={`${hit.doc_id}:${hit.line_start}`}
                        className={`panel knowledge-hit ${selectedId === hit.doc_id ? 'knowledge-hit-selected' : ''}`}
                        role="button"
                        tabIndex={0}
                        onClick={() => void open(hit.doc_id)}
                        onKeyDown={(event) => {
                          if (event.key === 'Enter' || event.key === ' ') {
                            event.preventDefault();
                            void open(hit.doc_id);
                          }
                        }}
                      >
                        <div className="card-top">
                          <div>
                            <h3>{hit.title}</h3>
                            <small className="muted">
                              {hit.path} · {hit.project_id ?? t('общий')}
                            </small>
                          </div>
                        </div>
                        <p className="excerpt">{markQuery(hit.excerpt, query)}</p>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <EmptyState>{t('Ничего не найдено. Очистите поиск, чтобы вернуть список.')}</EmptyState>
                )
              ) : list?.items.length ? (
                <ul className="hit-list">
                  {list.items.map((item) => (
                    <li
                      key={item.id}
                      className={`panel knowledge-hit ${selectedId === item.id ? 'knowledge-hit-selected' : ''}`}
                      role="button"
                      tabIndex={0}
                      onClick={() => void open(item.id)}
                      onKeyDown={(event) => {
                        if (event.key === 'Enter' || event.key === ' ') {
                          event.preventDefault();
                          void open(item.id);
                        }
                      }}
                    >
                      <div className="card-top">
                        <div>
                          <h3>{item.title}</h3>
                          <small className="muted">
                            {item.path} · {item.type} · {item.project_id ?? t('общий')}
                          </small>
                        </div>
                      </div>
                      <p className="excerpt">{item.excerpt}</p>
                      <small className="muted">{new Date(item.updated_at).toLocaleString()}</small>
                    </li>
                  ))}
                </ul>
              ) : (
                <EmptyState>{t('В базе знаний пока нет доступных документов.')}</EmptyState>
              )}
              {list && !query && (
                <nav className="knowledge-pagination" aria-label={t('Пагинация')}>
                  <button
                    className="button-secondary"
                    disabled={!offset}
                    onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
                  >
                    {t('Назад')}
                  </button>
                  <span>
                    {offset + 1}–{Math.min(offset + PAGE_SIZE, list.total)} {t('из')} {list.total}
                  </span>
                  <button
                    className="button-secondary"
                    disabled={offset + PAGE_SIZE >= list.total}
                    onClick={() => setOffset(offset + PAGE_SIZE)}
                  >
                    {t('Дальше')}
                  </button>
                </nav>
              )}
            </div>
            <aside className="panel knowledge-document knowledge-sidebar">
              {doc ? (
                <>
                  <div className="card-top">
                    <div>
                      <h2>{doc.title}</h2>
                      <small className="muted">{doc.path}</small>
                    </div>
                    <button className="button-secondary" onClick={() => setDoc(null)}>
                      {t('Закрыть')}
                    </button>
                  </div>
                  <div className="knowledge-connections">
                    <strong>{t('Связи')}</strong>
                    <div>
                      <small className="muted">{t('Входящие')}</small>
                      {selectedConnections.incoming.length ? (
                        <ul>
                          {selectedConnections.incoming.map((edge) => (
                            <li key={`${edge.source}-${edge.target}`}>
                              <button onClick={() => void open(edge.source)}>{edge.title}</button>
                            </li>
                          ))}
                        </ul>
                      ) : (
                        <p className="muted">{t('Нет входящих связей')}</p>
                      )}
                    </div>
                    <div>
                      <small className="muted">{t('Исходящие')}</small>
                      {selectedConnections.outgoing.length ? (
                        <ul>
                          {selectedConnections.outgoing.map((edge) => (
                            <li key={`${edge.source}-${edge.target}`}>
                              <button onClick={() => void open(edge.target)}>{edge.title}</button>
                            </li>
                          ))}
                        </ul>
                      ) : (
                        <p className="muted">{t('Нет исходящих связей')}</p>
                      )}
                    </div>
                  </div>
                  <div className="knowledge-actions">
                    <button className="button-secondary" onClick={() => setView('list')}>
                      {t('Открыть в списке')}
                    </button>
                    {obsidianUrl && (
                      <a className="button-secondary" href={obsidianUrl}>
                        {t('Открыть в Obsidian')}
                      </a>
                    )}
                    <button className="button-secondary" onClick={copyPath}>
                      {t('Скопировать путь')}
                    </button>
                  </div>
                  <MarkdownView content={doc.content} />
                </>
              ) : (
                <EmptyState>{t('Выберите заметку слева, чтобы прочитать её и увидеть связи.')}</EmptyState>
              )}
            </aside>
          </SplitPane>
        </section>
      ) : (
        <section className="knowledge-graph-full panel">
          <div className="knowledge-graph-head">
            {/* One compact row: the canvas gets the rest of the window height. */}
            <div className="knowledge-graph-controls">
              <div className="knowledge-graph-search">
                <input
                  value={graphSearch}
                  onChange={(event) => setGraphSearch(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' && graphSuggestions[0]) selectGraphNode(graphSuggestions[0].id);
                  }}
                  placeholder={t('Найти узел по названию…')}
                  aria-label={t('Поиск узла по названию')}
                />
                {graphSuggestions.length > 0 && (
                  <select
                    value=""
                    onChange={(event) => selectGraphNode(event.target.value)}
                    aria-label={t('Подсказки узлов')}
                  >
                    <option value="">{t('Подсказки…')}</option>
                    {graphSuggestions.map((node) => (
                      <option key={node.id} value={node.id}>
                        {node.title}
                      </option>
                    ))}
                  </select>
                )}
              </div>
              <div className="knowledge-graph-segmented" aria-label={t('Режим графа')}>
                {(['overview', 'projects', 'focus'] as const).map((value) => (
                  <button
                    key={value}
                    className={graphMode === value ? 'active' : 'button-secondary'}
                    onClick={() => setGraphMode(value)}
                  >
                    {value === 'overview' ? t('Общий') : value === 'projects' ? t('По проектам') : t('Фокус')}
                  </button>
                ))}
              </div>
              <div className="knowledge-graph-segmented" aria-label={t('Глубина соседства')}>
                {[1, 2].map((value) => (
                  <button
                    key={value}
                    className={graphDepth === value ? 'active' : 'button-secondary'}
                    onClick={() => setGraphDepth(value as 1 | 2)}
                  >
                    {value}
                  </button>
                ))}
              </div>
              <label className="knowledge-toggle">
                <input
                  type="checkbox"
                  checked={selectedEdgesOnly}
                  onChange={(event) => setSelectedEdgesOnly(event.target.checked)}
                />{' '}
                {t('Только связи выбранного')}
              </label>
              <button
                className="button-secondary"
                title={t('Вписать граф в холст')}
                onClick={() => setFitRequest((value) => value + 1)}
              >
                {t('Вписать')}
              </button>
              <button
                className="button-secondary"
                title={t('Сбросить расположение узлов')}
                onClick={() => setResetRequest((value) => value + 1)}
              >
                {t('Сбросить расположение')}
              </button>
              <button
                className="button-secondary"
                title={t('Сбросить фильтры и выбор')}
                onClick={() => {
                  setProject('');
                  setType('');
                  setSelectedEdgesOnly(false);
                  setSelectedId(null);
                }}
              >
                {t('Сбросить')}
              </button>
              <button
                className="button-secondary"
                title={t('Показать или скрыть легенду')}
                onClick={() => setLegendOpen((value) => !value)}
                aria-expanded={legendOpen}
              >
                {t('Легенда')}
              </button>
              <small className="muted knowledge-graph-count">
                {visibleGraph
                  ? t('{0} заметок · {1} связей', visibleGraph.nodes.length, visibleGraph.edges.length)
                  : t('Загрузка графа…')}
              </small>
            </div>
          </div>
          <div className="knowledge-legend" hidden={!legendOpen} aria-label={t('Легенда графа')}>
            <span className="knowledge-legend-item">
              <i className="knowledge-legend-swatch" /> {t('Проект / папка')}
            </span>
            <span className="knowledge-legend-item">
              <i className="knowledge-legend-swatch muted" /> {t('Призрачный узел')}
            </span>
            <span className="knowledge-legend-item">
              <i className="knowledge-legend-line" /> Wiki
            </span>
            <span className="knowledge-legend-item">
              <i className="knowledge-legend-line dashed" /> Embed
            </span>
            <span className="knowledge-legend-item">
              <i className="knowledge-legend-line dotted" /> Markdown
            </span>
          </div>
          <div className="knowledge-graph-workspace">
            {visibleGraph ? (
              <Suspense fallback={<Loading />}>
                <KnowledgeGraph
                  graph={visibleGraph}
                  selectedId={selectedId}
                  mode={graphMode}
                  depth={graphDepth}
                  selectedEdgesOnly={selectedEdgesOnly}
                  fitRequest={fitRequest}
                  resetRequest={resetRequest}
                  onSelect={(id) => {
                    if (id) selectGraphNode(id);
                    else setSelectedId(null);
                  }}
                  onOpen={(id) => void open(id)}
                />
              </Suspense>
            ) : (
              <Loading />
            )}
            {selectedId && doc && (
              <aside className="panel knowledge-graph-inspector">
                <div className="card-top">
                  <div>
                    <h2>{doc.title}</h2>
                    <small className="muted">{doc.path}</small>
                  </div>
                  <button className="button-secondary" onClick={() => setSelectedId(null)}>
                    {t('Закрыть')}
                  </button>
                </div>
                <div className="knowledge-connections">
                  <strong>{t('Связи')}</strong>
                  <small className="muted">
                    {selectedConnections.incoming.length} {t('входящих ·')} {selectedConnections.outgoing.length}{' '}
                    {t('исходящих')}
                  </small>
                  <small className="muted">
                    {t('Проект:')} {doc.project_id ?? t('Общее')}
                  </small>
                </div>
                <div className="knowledge-inspector-neighbours">
                  <strong>{t('Соседи')}</strong>
                  <ul>
                    {[...selectedConnections.incoming, ...selectedConnections.outgoing].map((edge) => (
                      <li key={`${edge.source}-${edge.target}`}>
                        <button onClick={() => selectGraphNode(edge.source === selectedId ? edge.target : edge.source)}>
                          {edge.title}
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
                <button className="button-secondary" onClick={() => setView('list')}>
                  {t('Открыть заметку')}
                </button>
              </aside>
            )}
          </div>
        </section>
      )}
    </div>
  );
}
