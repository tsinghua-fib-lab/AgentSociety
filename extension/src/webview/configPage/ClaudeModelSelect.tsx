import * as React from 'react';
import { Select } from 'antd';
import type { ClaudeModelOption } from './claudeCodeTypes';

export interface ClaudeModelSelectProps {
  id?: string;
  value?: string;
  onChange?: (value: string) => void;
  models: ClaudeModelOption[];
  placeholder: string;
  disabled?: boolean;
  loading?: boolean;
}

export const ClaudeModelSelect: React.FC<ClaudeModelSelectProps> = ({
  id,
  value,
  onChange,
  models,
  placeholder,
  disabled,
  loading,
}) => {
  const [search, setSearch] = React.useState('');
  const options = React.useMemo(
    () => {
      const choices = models.map((m) => ({
        value: m.id,
        label: m.label ? `${m.label} (${m.id})` : m.id,
      }));
      for (const id of [value?.trim(), search.trim()]) {
        if (id && !choices.some((choice) => choice.value === id)) {
          choices.push({ value: id, label: id });
        }
      }
      return choices;
    },
    [models, value, search]
  );

  return (
    <Select
      id={id}
      showSearch
      allowClear
      placeholder={placeholder}
      value={value?.trim() ? value : undefined}
      searchValue={search}
      onSearch={setSearch}
      onOpenChange={(open) => { if (!open) { setSearch(''); } }}
      onChange={(next) => { setSearch(''); onChange?.(next ?? ''); }}
      disabled={disabled}
      loading={loading}
      options={options}
      optionFilterProp="label"
      style={{ width: '100%' }}
      popupMatchSelectWidth
      listHeight={320}
      notFoundContent={placeholder}
    />
  );
};
