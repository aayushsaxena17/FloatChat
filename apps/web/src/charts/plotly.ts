// Plotly loader (ADR-0061): the cartesian bundle (scatter, histogram) typed through
// @types/plotly.js. The `map` chart kind is rendered by MapLibre, never by Plotly.
import Plotly from "plotly.js-cartesian-dist-min";

export default Plotly;
