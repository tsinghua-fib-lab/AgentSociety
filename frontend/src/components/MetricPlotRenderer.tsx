import createPlotlyComponent from 'react-plotly.js/factory';
import Plotly from 'plotly.js/lib/core';
import scatter from 'plotly.js/lib/scatter';

// Replay metrics only use scatter traces (lines and markers).
Plotly.register([scatter]);
const MetricPlot = createPlotlyComponent(Plotly);
export default MetricPlot;
