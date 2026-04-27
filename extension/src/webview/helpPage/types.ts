export interface VSCodeAPI {
  postMessage: (message: unknown) => void;
  getState: () => unknown;
  setState: (state: unknown) => void;
}

declare function acquireVsCodeApi(): VSCodeAPI;

export interface HelpSection {
  id: string;
  title: string;
  icon: string;
  content: HelpItem[];
}

export interface HelpItem {
  title: string;
  description: string;
  commands?: string[];
  tips?: string[];
}
