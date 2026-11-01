export type GraphCommit = { sha: string; parents: string[] };
export type GraphEdge = {
  from: string;
  to: string;
  start: number;
  end: number;
  kind: 'parent' | 'continuation' | 'join';
};

/** Lay out a topologically ordered log, retaining each pending parent in its lane. */
export function layoutGraph<T extends GraphCommit>(commits: T[]) {
  const lanes: (string | null)[] = [];
  return commits.map((commit) => {
    let lane = lanes.indexOf(commit.sha);
    if (lane < 0) {
      lane = lanes.indexOf(null);
      if (lane < 0) lane = lanes.length;
      lanes[lane] = commit.sha;
    }
    const edges: GraphEdge[] = [];
    lanes.forEach((sha, index) => {
      if (!sha || index === lane) return;
      if (sha === commit.sha) {
        edges.push({ from: sha, to: sha, start: index, end: lane, kind: 'join' });
        lanes[index] = null;
      } else {
        edges.push({ from: sha, to: sha, start: index, end: index, kind: 'continuation' });
      }
    });
    lanes[lane] = null;
    commit.parents.forEach((parent, index) => {
      let target = index === 0 ? lane : lanes.indexOf(parent);
      if (index === 0) lanes[lane] = parent;
      if (target < 0) {
        target = lanes.indexOf(null);
        if (target < 0) target = lanes.length;
        lanes[target] = parent;
      }
      edges.push({ from: commit.sha, to: parent, start: lane, end: target, kind: 'parent' });
    });
    return { commit, lane, edges };
  });
}
