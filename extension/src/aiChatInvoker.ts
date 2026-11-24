import * as vscode from 'vscode';
import { localize } from './i18n';
import { getMainOutputChannel } from './shared/outputChannels';

const providers = [
  { id: 'claude-code', extensionId: 'anthropic.claude-code', label: 'Claude Code', command: 'claude-vscode.editor.open' },
  { id: 'codex', extensionId: 'openai.chatgpt', label: 'Codex', command: 'chatgpt.openSidebar' },
  { id: 'cursor', label: 'Cursor Chat', command: 'cursor.chat' },
  { id: 'vscode-chat', label: 'VS Code Chat', command: 'workbench.action.chat.open' },
] as const;

type ChatProvider = typeof providers[number];

export class AIChatInvoker {
  private async availableProviders(): Promise<ChatProvider[]> {
    const commands = new Set(await vscode.commands.getCommands(true));
    return providers.filter(provider => {
      if (commands.has(provider.command)) { return true; }
      // 冷启动时，助手的命令可能尚待首次调用激活。
      if (!('extensionId' in provider)) { return false; }
      const manifest = vscode.extensions.getExtension(provider.extensionId)?.packageJSON;
      return manifest?.contributes?.commands?.some((entry: { command: string }) => entry.command === provider.command);
    });
  }

  private preferredId(): string {
    return vscode.workspace.getConfiguration('aiSocialScientist').get<string>('preferredAiChat', '');
  }

  private async choose(available: ChatProvider[], title: string): Promise<ChatProvider | undefined> {
    if (!available.length) {
      void vscode.window.showInformationMessage(localize('extension.aiChat.unavailable'));
      return undefined;
    }
    const preferred = this.preferredId();
    const choice = await vscode.window.showQuickPick(available.map(provider => ({
      label: provider.label,
      description: provider.id === preferred ? localize('extension.aiChat.currentDefault') : undefined,
      provider,
    })), { title });
    return choice?.provider;
  }

  /** 打开默认助手；有多个可用助手且未设置默认值时，仅为本次对话选取。 */
  async invokeChat(): Promise<boolean> {
    const available = await this.availableProviders();
    const preferred = this.preferredId();
    const provider = available.find(entry => entry.id === preferred)
      ?? (available.length === 1 ? available[0] : await this.choose(available, localize('extension.aiChat.chooseOnce')));
    if (!provider) { return false; }
    try {
      await vscode.commands.executeCommand(provider.command);
      return true;
    } catch (error) {
      getMainOutputChannel().appendLine(`[Chat] ${provider.command}: ${error}`);
      void vscode.window.showErrorMessage(localize('extension.aiChat.openFailed', provider.label));
      return false;
    }
  }

  /** 保存下一次左键打开的助手，保留当前对话。 */
  async pickProvider(): Promise<void> {
    const provider = await this.choose(await this.availableProviders(), localize('extension.aiChat.chooseDefault'));
    if (provider) {
      const config = vscode.workspace.getConfiguration('aiSocialScientist');
      const target = config.inspect<string>('preferredAiChat')?.workspaceValue === undefined
        ? vscode.ConfigurationTarget.Global : vscode.ConfigurationTarget.Workspace;
      await config.update('preferredAiChat', provider.id, target);
    }
  }
}
