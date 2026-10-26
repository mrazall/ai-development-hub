declare module 'cytoscape-fcose' {
  const extension: (cy: typeof import('cytoscape')) => void;
  export default extension;
}
