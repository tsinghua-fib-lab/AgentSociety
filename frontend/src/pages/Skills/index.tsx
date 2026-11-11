import { useAsyncResource } from '../../hooks/useAsyncResource';
import { useCallback, useRef, useState } from "react";
import {
  Button, message, Modal, Space, Tag,
  Form, Input, Upload, Typography,
} from "antd";
import { ProTable, ProColumns } from "@ant-design/pro-components";
import { ActionType } from "@ant-design/pro-table";
import { useTranslation } from "react-i18next";
import { fetchCustom } from "../../components/fetch";
import {
  PlusOutlined, UploadOutlined, EyeOutlined, ScanOutlined,
} from "@ant-design/icons";

const { TextArea } = Input;
const { Text, Paragraph } = Typography;

interface SkillItem {
  skill_id: string;
  name: string;
  description: string;
  source: string;
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
  const [creating, setCreating] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [uploading, setUploading] = useState(false);
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

  const operationError = (data: { detail?: unknown; message?: string }) =>
    typeof data.detail === 'string' ? data.detail : data.message || t("skill.messages.operationFailed");

  const handleView = async (skillId: string) => {
    try {
      const res = await fetchCustom(`/api/v1/agent-skills/${encodeURIComponent(skillId)}/info`);
      const data = await res.json();
      if (res.ok && data.success) {
        setViewSkillName(data.name);
        setViewContent(data.skill_md || "(empty)");
        setViewOpen(true);
      } else {
        message.error(operationError(data));
      }
    } catch {
      message.error(t("skill.messages.operationFailed"));
    }
  };

  const handleScan = async () => {
    if (scanning) return;
    setScanning(true);
    try {
      const res = await fetchCustom("/api/v1/agent-skills/scan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      const data = await res.json();
      if (res.ok && data.success) {
        message.success(`${t("skill.messages.scanSuccess")} — ${data.message}`);
        fetchSkills();
      } else {
        message.error(operationError(data));
      }
    } catch {
      message.error(t("skill.messages.operationFailed"));
    } finally {
      setScanning(false);
    }
  };

  const handleCreate = async () => {
    if (creating) return;
    // Field validation already explains the problem next to the input.
    const values = await createForm.validateFields().catch(() => null);
    if (!values) return;
    setCreating(true);
    try {
      const payload = {
        name: values.name.trim(),
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
      if (res.ok && data.success) {
        message.success(t("skill.messages.createSuccess"));
        setCreateOpen(false);
        createForm.resetFields();
        fetchSkills();
      } else {
        message.error(operationError(data));
      }
    } catch {
      message.error(t("skill.messages.operationFailed"));
    } finally {
      setCreating(false);
    }
  };

  const handleUpload = async (file: File) => {
    if (uploading) return false;
    setUploading(true);
    const formData = new FormData();
    formData.append("file", file);
    try {
      const res = await fetchCustom("/api/v1/agent-skills/upload", {
        method: "POST",
        body: formData,
      });
      const data = await res.json();
      if (res.ok && data.success) {
        message.success(`${t("skill.messages.uploadSuccess")} — ${data.name}`);
        fetchSkills();
      } else {
        message.error(operationError(data));
      }
    } catch {
      message.error(t("skill.messages.operationFailed"));
    } finally {
      setUploading(false);
    }
    return false;
  };

  const sourceLabel = (source: string) => {
    if (source === "built-in") return t("skill.source.builtin");
    if (source === "custom") return t("skill.source.custom");
    if (source === "env" || source.startsWith("env:")) return `${t("skill.source.env")}`;
    return source;
  };

  const sourceColor = (source: string) => {
    if (source === "built-in") return "blue";
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
        { text: t("skill.source.builtin"), value: "built-in" },
        { text: t("skill.source.custom"), value: "custom" },
        { text: t("skill.source.env"), value: "env" },
      ],
      onFilter: (value, record) => record.source === value || record.source.startsWith(value as string),
    },
    {
      title: t("skill.columns.script"),
      dataIndex: "script",
      width: 180,
      ellipsis: true,
      render: (_, record) => (
        record.script
          ? <Tag
              color="purple"
              title={record.script}
              style={{
                maxWidth: '100%',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                verticalAlign: 'middle',
                marginInlineEnd: 0,
              }}
            >{record.script}</Tag>
          : <Text type="secondary">{t("skill.type.promptOnly")}</Text>
      ),
    },
    {
      title: t("skill.columns.actions"),
      width: 100,
      render: (_, record) => (
        <Space size="small">
          <Button type="link" size="small" icon={<EyeOutlined />} onClick={() => handleView(record.skill_id)}>
            {t("skill.actions.view")}
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      <Paragraph type="secondary">{t("skill.description")}</Paragraph>
      <ProTable<SkillItem>
        headerTitle={t("skill.title")}
        actionRef={actionRef}
        rowKey="skill_id"
        columns={columns}
        dataSource={skills}
        loading={loading}
        search={false}
        pagination={false}
        options={{ reload: fetchSkills }}
        scroll={{ x: 1000 }}
        toolBarRender={() => [
          <Button key="scan" icon={<ScanOutlined />} onClick={handleScan} loading={scanning}>
            {t("skill.actions.scan")}
          </Button>,
          <Upload
            key="upload"
            accept=".zip"
            showUploadList={false}
            disabled={uploading}
            beforeUpload={(file) => { handleUpload(file); return false; }}
          >
            <Button icon={<UploadOutlined />} loading={uploading}>{t("skill.actions.upload")}</Button>
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
        onCancel={() => { if (!creating) setCreateOpen(false); }}
        onOk={handleCreate}
        confirmLoading={creating}
        cancelButtonProps={{ disabled: creating }}
        closable={!creating}
        maskClosable={!creating}
        keyboard={!creating}
        width={720}
        destroyOnClose
      >
        <Form form={createForm} layout="vertical" preserve={false}>
          <Form.Item
            name="name"
            label={t("skill.create.name")}
            rules={[{ required: true, whitespace: true, message: t("skill.create.nameRequired") }]}
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
