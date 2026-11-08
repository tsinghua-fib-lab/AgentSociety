import * as React from 'react';
import { Collapse, Form, Select } from 'antd';
import type { TFunction } from 'i18next';

/**
 * 「推理（thinking）开关」下拉。
 *
 * 值直接就是写进 .env 的字符串：`''` / `'on'` / `'off'`。
 * 空串与「未设置」等价 —— 后端 `_env_str` 把 unset 与 blank 一视同仁当作 None，
 * 即不发送任何推理相关参数（见 agentsociety2/config/config.py 的 get_llm_thinking）。
 * 因此不需要 ENV_LLM_SLOT 那样的哨兵 + 双向映射。
 */
export const THINKING_INHERIT = '';
export const THINKING_ON = 'on';
export const THINKING_OFF = 'off';

type Props = {
  t: TFunction;
  /** `coder` 时「继承」文案为「跟随默认 LLM」，与专用模型 tab 的既有口径一致。 */
  scope?: 'default' | 'coder';
  value?: string;
  onChange?: (value: string) => void;
};

export function ThinkingSelect({ t, scope = 'default', value, onChange }: Props) {
  // 「继承」文案同时用作 placeholder：即使 antd 对 value='' 回退到 placeholder
  // 而不是渲染选项 label，用户看到的也是同一句话，渲染差异不影响语义。
  const inheritLabel = t(
    scope === 'coder' ? 'configPage.thinking.inheritCoder' : 'configPage.thinking.inheritDefault'
  );
  const options = React.useMemo(
    () => [
      { value: THINKING_INHERIT, label: inheritLabel },
      { value: THINKING_ON, label: t('configPage.thinking.on') },
      { value: THINKING_OFF, label: t('configPage.thinking.off') },
    ],
    [inheritLabel, t]
  );

  return (
    <Select
      value={value ?? THINKING_INHERIT}
      onChange={(next) => onChange?.(next ?? THINKING_INHERIT)}
      placeholder={inheritLabel}
      options={options}
      style={{ width: '100%' }}
      popupMatchSelectWidth
    />
  );
}

/** Advanced wire settings stay separate from the everyday on/off choice. */
export function LlmApiTypeField({ t, scope = 'default' }: Pick<Props, 't' | 'scope'>) {
  const form = Form.useFormInstance();
  const ownApiType = Form.useWatch(scope === 'coder' ? 'coderLlmApiType' : 'llmApiType', form);
  const defaultApiType = Form.useWatch('llmApiType', form);
  const apiType = ownApiType || defaultApiType || 'openai';
  const formatName = scope === 'coder' ? 'coderLlmThinkingFormat' : 'llmThinkingFormat';
  return <Collapse size="small" style={{ marginBottom: 16 }} items={[{
    key: 'thinking-options', label: t('configPage.thinking.advanced'), forceRender: true,
    children: <>
      <Form.Item name={scope === 'coder' ? 'coderLlmApiType' : 'llmApiType'} label={t('configPage.thinking.apiType')} tooltip={t('configPage.thinking.apiTypeHint')}>
        <Select aria-label={t(scope === 'coder' ? 'configPage.thinking.coderApiType' : 'configPage.thinking.apiType')} options={[
          ...(scope === 'coder' ? [{ value: '', label: t('configPage.thinking.inheritCoder') }] : []),
          { value: 'openai', label: 'OpenAI Chat Completions' },
          { value: 'anthropic', label: 'Anthropic Messages' },
        ]} />
      </Form.Item>
      <Form.Item hidden={apiType === 'anthropic'} name={formatName} label={t('configPage.thinking.format')} tooltip={t('configPage.thinking.formatHint')} style={{ marginBottom: 0 }}>
        <Select aria-label={t(scope === 'coder' ? 'configPage.thinking.coderFormat' : 'configPage.thinking.format')} disabled={apiType === 'anthropic'} options={[
          { value: '', label: t(scope === 'coder' ? 'configPage.thinking.inheritCoder' : 'configPage.thinking.standard') },
          { value: 'thinking', label: 'thinking.type' },
          { value: 'enable_thinking', label: 'enable_thinking' },
          { value: 'chat_template_kwargs', label: 'chat_template_kwargs.enable_thinking' },
          { value: 'reasoning', label: 'reasoning.enabled' },
        ]} />
      </Form.Item>
    </>,
  }]} />;
}
