import * as vscode from 'vscode';

export const OUTPUT_CHANNEL_MAIN = 'AI Social Scientist';
export const OUTPUT_CHANNEL_BACKEND = 'AI Social Scientist Backend';
export const OUTPUT_CHANNEL_GATEWAY = 'AI CLI Gateway';

const channels = new Map<string, vscode.OutputChannel>();

function recreateChannel(name: string): vscode.OutputChannel {
  channels.delete(name);
  const channel = vscode.window.createOutputChannel(name);
  channels.set(name, channel);
  return channel;
}

function channelIsUsable(channel: vscode.OutputChannel): boolean {
  try {
    channel.append('');
    return true;
  } catch {
    return false;
  }
}

export function getSharedOutputChannel(name: string): vscode.OutputChannel {
  const existing = channels.get(name);
  if (existing && channelIsUsable(existing)) {
    return existing;
  }
  return recreateChannel(name);
}

export function appendSharedOutputLine(name: string, line: string): void {
  try {
    getSharedOutputChannel(name).appendLine(line);
  } catch (error) {
    if (error instanceof Error && error.message.includes('Channel has been closed')) {
      recreateChannel(name).appendLine(line);
      return;
    }
    throw error;
  }
}

export function getMainOutputChannel(): vscode.OutputChannel {
  return getSharedOutputChannel(OUTPUT_CHANNEL_MAIN);
}
