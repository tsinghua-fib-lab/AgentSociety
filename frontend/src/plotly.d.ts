declare module 'plotly.js/lib/core' {
    import * as Plotly from 'plotly.js';
    export = Plotly;
}
declare module 'plotly.js/lib/scatter' {
    const scatter: import('plotly.js').PlotlyModule;
    export = scatter;
}
