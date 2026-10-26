export type KnowledgeGraphResponse = {
  nodes: Array<{
    id: string;
    title: string;
    path: string | null;
    project_id: string | null;
    degree: number;
    ghost: boolean;
    type?: string;
  }>;
  edges: Array<{ source: string; target: string; type?: string }>;
};

type Rng = () => number;

function mulberry32(seed: number): Rng {
  return () => {
    let value = (seed += 0x6d2b79f5);
    value = Math.imul(value ^ (value >>> 15), value | 1);
    value ^= value + Math.imul(value ^ (value >>> 7), value | 61);
    return ((value ^ (value >>> 14)) >>> 0) / 4294967296;
  };
}

const fragments = [
  'Архитектура устойчивого хранилища знаний и правила публикации',
  'План миграции рабочих процессов между окружениями и командами',
  'Наблюдаемость фоновых задач, ретраи и разбор отказов интеграций',
  'Исследование связей документов, источников и решений проекта',
  'Практика безопасной работы с локальными секретами и доступами',
  'Руководство по проверке качества поисковой выдачи и контекста',
];
const projects = ['atlas', 'lighthouse', 'orion', 'общая библиотека', 'архив экспериментов'];
const folders = ['research', 'decisions', 'runbooks', 'meetings', 'design', 'archive'];

function title(index: number, ghost: boolean): string {
  const base = fragments[index % fragments.length];
  const suffix = ` — ${projects[index % projects.length]}, ${folders[(index * 3) % folders.length]}, редакция ${index + 1}`;
  return `${ghost ? 'Внешняя ссылка: ' : ''}${base}${suffix}`.slice(0, 90);
}

/** Build reproducible, intentionally non-uniform graph data for browser readability checks. */
export function makeGraphDataset(nodeCount: number, edgeCount: number, seed = 3): KnowledgeGraphResponse {
  if (nodeCount < 2 || edgeCount < 1 || edgeCount > (nodeCount * (nodeCount - 1)) / 2) {
    throw new RangeError('graph dimensions cannot contain the requested edges');
  }
  const random = mulberry32(seed);
  const ghostCount = Math.max(3, Math.round(nodeCount * 0.04));
  const nodes = Array.from({ length: nodeCount }, (_, index) => {
    const ghost = index >= nodeCount - ghostCount;
    const id = `synthetic-${seed}-${index + 1}`;
    return {
      id,
      title: title(index, ghost),
      path: `${folders[index % folders.length]}/${id}.md`,
      project_id: ghost ? null : `project-${projects[index % projects.length].replaceAll(' ', '-')}`,
      degree: 0,
      ghost,
      type: index % 7 === 0 ? 'decision' : 'markdown',
    };
  });

  // Preferential attachment creates hubs and small peripheral clusters without relying on layout randomness.
  const weights = nodes.map(() => 1);
  const pairs = new Set<string>();
  const edges: KnowledgeGraphResponse['edges'] = [];
  const addEdge = (a: number, b: number, type: string) => {
    if (a === b) return false;
    const source = Math.min(a, b);
    const target = Math.max(a, b);
    const key = `${source}:${target}`;
    if (pairs.has(key)) return false;
    pairs.add(key);
    edges.push({ source: nodes[source].id, target: nodes[target].id, type });
    weights[source] += 1;
    weights[target] += 1;
    nodes[source].degree += 1;
    nodes[target].degree += 1;
    return true;
  };
  for (let index = 1; index < nodeCount && edges.length < edgeCount; index += 1) {
    const target = Math.floor(random() * index);
    addEdge(index, target, index % 5 === 0 ? 'embed' : 'wiki');
  }
  while (edges.length < edgeCount) {
    const total = weights.reduce((sum, weight) => sum + weight, 0);
    let pick = random() * total;
    let source = 0;
    for (; source < weights.length - 1 && pick > weights[source]; source += 1) pick -= weights[source];
    const target = Math.floor(random() * nodeCount);
    if (addEdge(source, target, edges.length % 4 === 0 ? 'markdown' : edges.length % 3 === 0 ? 'embed' : 'wiki'))
      continue;
  }
  return { nodes, edges };
}

export const graph100x300 = makeGraphDataset(100, 300, 1003);
export const graph300x1000 = makeGraphDataset(300, 1000, 3007);
