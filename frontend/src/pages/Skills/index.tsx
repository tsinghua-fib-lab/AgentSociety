import { useAsyncResource } from '../../hooks/useAsyncResource';
import { useCallback, useRef, useState } from "react";
import {
  Button, message, Modal, Space, Tag, Popconfirm,
  Form, Input, Upload, Typography, Switch,
} from "antd";
import { ProTable, ProColumns } from "@ant-design/pro-components";
import { ActionType } from "@ant-design/pro-table";
import { useTranslation } from "react-i18next";
import { fetchCustom } from "../../components/fetch";
import {
  PlusOutlined, UploadOutlined, ReloadOutlined,
  DeleteOutlined, EyeOutlined, ScanOutlined,
} from "@ant-design/icons";

const { TextArea } = Input;
const { Text } = Typography;

interface SkillItem {
  name: string;
  description: string;
  source: string;
  enabled: boolean;
  path: string;
  has_skill_md: boolean;
  script: string;
}

const SkillsPage = () => {
  const { t } = useTranslation();
  const actionRef = useRef<ActionType | undefined>(undefined);
  const [createOpen, setCreateOpen] = useState(false);
  const [viewOpen, setViewOpen] = useState(false);
  const [viewContent, setViewContent] = useState("");
  const [viewSkillName, setViewSkillName] = useState("");
  const [createForm] = Form.useForm();

    const loadResource = useCallback(async (): Promise<SkillItem[]> => {
        const response = await fetchCustom('/api/v1/agent-skills/list');
        if (!response.ok) throw new Error(await response.text());
        const data = await response.json();
        if (!data.success) throw new Error(data.message || "Failed to load skills");
        return data.skills || [];
    }, []);
    const handleLoadError = useCallback((error: unknown) => {
        console.error('Failed to load skills:', error);
        message.error(t("skill.messages.operationFailed"));
    }, [t]);
    const { data: skills, loading, reload: fetchSkills } = useAsyncResource(
        loadResource, handleLoadError, [],
    );

  const handleToggleEnabled = async (name: string, enabled: boolean) => {
    try {
      const path = enabled ? "/api/v1/agent-skills/enable" : "/api/v1/agent-skills/disable";
      const res = await fetchCustom(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      });
      const data = await res.json();
      if (data.success) {
        message.success(enabled ? t("skill.messages.enableSuccess") : t("skill.messages.disableSuccess"));
        fetchSkills();
      } else {
        message.error(data.message || t("skill.messages.operationFailed"));
      }
    } catch {
      message.error(t("skill.messages.operationFailed"));
    }
  };

  const handleReload = async (name: string) => {
    try {
      const res = await fetchCustom("/api/v1/agent-skills/reload", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      });
      const data = await res.json();
      if (data.success) {
        message.success(t("skill.messages.reloadSuccess"));
        fetchSkills();
      } else {
        message.error(data.message || t("skill.messages.operationFailed"));
      }
    } catch {
      message.error(t("skill.messages.operationFailed"));
    }
  };

  const handleRemove = async (name: string) => {
    try {
      const res = await fetchCustom("/api/v1/agent-skills/remove", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      });
      const data = await res.json();
      if (data.success) {
        message.success(t("skill.messages.removeSuccess"));
        fetchSkills();
      } else {
        message.error(data.message || t("skill.messages.operationFailed"));
      }
    } catch {
      message.error(t("skill.messages.operationFailed"));
    }
  };

  const handleView = async (name: string) => {
    try {
      const res = await fetchCustom(`/api/v1/agent-skills/${encodeURIComponent(name)}/info`);
      const data = await res.json();
      if (data.success) {
        setViewSkillName(data.name);
        setViewContent(data.skill_md || "(empty)");
        setViewOpen(true);
      } else {
        message.error(t("skill.messages.operationFailed"));
      }
    } catch {
      message.error(t("skill.messages.operationFailed"));
    }
  };

  const handleScan = async () => {
    try {
      const res = await fetchCustom("/api/v1/agent-skills/scan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      const data = await res.json();
      if (data.success) {
        message.success(`${t("skill.messages.scanSuccess")} — ${data.message}`);
        fetchSkills();
      } else {
        message.error(data.message || t("skill.messages.operationFailed"));
      }
    } catch {
      message.error(t("skill.messages.operationFailed"));
    }
  };

  const handleCreate = async () => {
    try {
      const values = await createForm.validateFields();
      const payload = {
        name: values.name,
        description: values.description || "",
        script: values.script || "",
        body: values.body || "",
        script_content: values.script_content || "",
      };
      const res = await fetchCustom("/api/v1/agent-skills/create", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (data.success) {
        message.success(t("skill.messages.createSuccess"));
        setCreateOpen(false);
        createForm.resetFields();
        fetchSkills();
      } else {
        message.error(data.message || t("skill.messages.operationFailed"));
      }
    } catch {
      message.error(t("skill.messages.operationFailed"));
    }
  };

  const handleUpload = async (file: File) => {
    const formData = new FormData();
    formData.append("file", file);
    try {
      const res = await fetchCustom("/api/v1/agent-skills/upload", {
        method: "POST",
        body: formData,
      });
      const data = await res.json();
      if (data.success) {
        message.success(`${t("skill.messages.uploadSuccess")} — ${data.name}`);
        fetchSkills();
      } else {
        message.error(data.message || t("skill.messages.operationFailed"));
      }
    } catch {
      message.error(t("skill.messages.operationFailed"));
    }
    return false;
  };

  const sourceLabel = (source: string) => {
    if (source === "builtin") return t("skill.source.builtin");
    if (source === "custom") return t("skill.source.custom");
    if (source.startsWith("env:")) return `${t("skill.source.env")}`;
    return source;
  };

  const sourceColor = (source: string) => {
    if (source === "builtin") return "blue";
    if (source === "custom") return "green";
    return "orange";
  };

  const columns: ProColumns<SkillItem>[] = [
    {
      title: t("skill.columns.name"),
      dataIndex: "name",
      width: 140,
      render: (_, record) => <Text strong>{record.name}</Text>,
    },
    {
      title: t("skill.columns.description"),
      dataIndex: "description",
      ellipsis: true,
    },
    {
      title: t("skill.columns.source"),
      dataIndex: "source",
      width: 100,
      render: (_, record) => (
        <Tag color={sourceColor(record.source)}>{sourceLabel(record.source)}</Tag>
      ),
      filters: [
        { text: t("skill.source.builtin"), value: "builtin" },
        { text: t("skill.source.custom"), value: "custom" },
        { text: t("skill.source.env"), value: "env:" },
      ],
      onFilter: (value, record) => record.source === value || record.source.startsWith(value as string),
    },
    {
      title: t("skill.columns.enabled"),
      dataIndex: "enabled",
      width: 120,
      render: (_, record) =>
        record.source === "builtin" ? (
          <Tag color="blue">{t("skill.status.builtinAlwaysOn")}</Tag>
        ) : (
          <Switch
            checked={record.enabled}
            checkedChildren={t("skill.status.enabled")}
            unCheckedChildren={t("skill.status.disabled")}
            onChange={(checked) => handleToggleEnabled(record.name, checked)}
          />
        ),
    },
    {
      title: t("skill.columns.script"),
      dataIndex: "script",
      width: 120,
      render: (_, record) => (
        record.script
          ? <Tag color="purple">{record.script}</Tag>
          : <Text type="secondary">{t("skill.type.promptOnly")}</Text>
      ),
    },
    {
      title: t("skill.columns.actions"),
      width: 200,
      render: (_, record) => (
        <Space size="small">
          <Button type="link" size="small" icon={<EyeOutlined />} onClick={() => handleView(record.name)}>
            {t("skill.actions.view")}
          </Button>
          <Button type="link" size="small" icon={<ReloadOutlined />} onClick={() => handleReload(record.name)}>
            {t("skill.actions.reload")}
          </Button>
          {record.source === "custom" && (
            <Popconfirm
              title={t("skill.messages.removeConfirm")}
              onConfirm={() => handleRemove(record.name)}
            >
              <Button type="link" size="small" danger icon={<DeleteOutlined />}>
                {t("skill.actions.remove")}
              </Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      <ProTable<SkillItem>
        headerTitle={t("skill.title")}
        actionRef={actionRef}
        rowKey="name"
        columns={columns}
        dataSource={skills}
        loading={loading}
        search={false}
        pagination={false}
        toolBarRender={() => [
          <Button key="scan" icon={<ScanOutlined />} onClick={handleScan}>
            {t("skill.actions.scan")}
          </Button>,
          <Upload
            key="upload"
            accept=".zip"
            showUploadList={false}
            beforeUpload={(file) => { handleUpload(file); return false; }}
          >
            <Button icon={<UploadOutlined />}>{t("skill.actions.upload")}</Button>
          </Upload>,
          <Button key="create" type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
            {t("skill.actions.create")}
          </Button>,
        ]}
      />

      {/* Create Modal */}
      <Modal
        title={t("skill.create.title")}
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onOk={handleCreate}
        width={720}
        destroyOnClose
      >
        <Form form={createForm} layout="vertical" preserve={false}>
          <Form.Item
            name="name"
            label={t("skill.create.name")}
            rules={[{ required: true, message: t("skill.create.nameRequired") }]}
          >
            <Input placeholder={t("skill.create.namePlaceholder")} />
          </Form.Item>
          <Form.Item name="description" label={t("skill.create.description")}>
            <Input placeholder={t("skill.create.descriptionPlaceholder")} />
          </Form.Item>
          <Form.Item name="script" label={t("skill.create.script")}>
            <Input placeholder={t("skill.create.scriptPlaceholder")} />
          </Form.Item>
          <Form.Item name="body" label={t("skill.create.body")}>
            <TextArea rows={8} placeholder={t("skill.create.bodyPlaceholder")} />
          </Form.Item>
          <Form.Item
            noStyle
            shouldUpdate={(prev, cur) => prev.script !== cur.script}
          >
            {({ getFieldValue }) =>
              getFieldValue("script") ? (
                <Form.Item name="script_content" label={t("skill.create.scriptContent")}>
                  <TextArea rows={10} placeholder={t("skill.create.scriptContentPlaceholder")} style={{ fontFamily: "monospace" }} />
                </Form.Item>
              ) : null
            }
          </Form.Item>
        </Form>
      </Modal>

      {/* View Modal */}
      <Modal
        title={`${t("skill.view.title")} — ${viewSkillName}`}
        open={viewOpen}
        onCancel={() => setViewOpen(false)}
        footer={null}
        width={720}
      >
        <pre style={{
          background: "#f5f5f5",
          padding: 16,
          borderRadius: 8,
          maxHeight: 500,
          overflow: "auto",
          fontSize: 13,
          lineHeight: 1.6,
          whiteSpace: "pre-wrap",
          wordBreak: "break-word",
        }}>
          {viewContent}
        </pre>
      </Modal>
    </div>
  );
};

export default SkillsPage;
