import React, { useRef, useEffect, useCallback } from 'react';
import Editor from '@monaco-editor/react';
import type * as Monaco from 'monaco-editor';

export interface MonacoSuggestionItem {
  label: string;
  detail?: string;
  children?: MonacoSuggestionItem[];
}

interface MonacoPromptEditorProps {
  value?: string;
  onChange?: (value: string | undefined) => void;
  height?: string;
  suggestions?: MonacoSuggestionItem[];
  editorId?: string;
}

const getCurrentPath = (textUntilPosition: string): string[] => {
  const match = textUntilPosition.match(/[\w.]+$/);
  return match ? match[0].split('.') : [];
};

const getSuggestionsForPath = (
  path: string[],
  suggestionItems: MonacoSuggestionItem[]
): MonacoSuggestionItem[] => {
  if (path.length <= 1) {
    return suggestionItems;
  }

  let currentSuggestions = suggestionItems;
  for (let i = 0; i < path.length - 1; i++) {
    const currentSegment = path[i];
    const matchingSuggestion = currentSuggestions.find(s => s.label === currentSegment);
    if (matchingSuggestion && matchingSuggestion.children) {
      currentSuggestions = matchingSuggestion.children;
    } else {
      return [];
    }
  }
  return currentSuggestions;
};

const MonacoPromptEditor: React.FC<MonacoPromptEditorProps> = ({
  value = '',
  onChange,
  height = '200px',
  suggestions = [],
  editorId = 'default'
}) => {
  const providerRef = useRef<Monaco.IDisposable | null>(null);
  const editorRef = useRef<Monaco.editor.IStandaloneCodeEditor | null>(null);
  const monacoRef = useRef<typeof Monaco | null>(null);

  const registerCompletionProvider = useCallback((monaco: typeof Monaco) => {
    if (providerRef.current) {
      providerRef.current.dispose();
      providerRef.current = null;
    }

    const uniqueLanguageId = `markdown-${editorId}`;

    if (!monaco.languages.getLanguages().some((lang) => lang.id === uniqueLanguageId)) {
      monaco.languages.register({
        id: uniqueLanguageId,
        extensions: ['.md'],
        aliases: ['Markdown', uniqueLanguageId],
        mimetypes: ['text/markdown']
      });
    }

    providerRef.current = monaco.languages.registerCompletionItemProvider(uniqueLanguageId, {
      triggerCharacters: ['$', '.', '{', ' '],
      provideCompletionItems: (model: Monaco.editor.ITextModel, position: Monaco.Position) => {
        const textUntilPosition = model.getValueInRange({
          startLineNumber: position.lineNumber,
          startColumn: 1,
          endLineNumber: position.lineNumber,
          endColumn: position.column
        });

        const hasDollar = textUntilPosition.endsWith('$');
        const hasBrace = textUntilPosition.endsWith('{');
        const hasDot = textUntilPosition.endsWith('.');
        const hasSpace = textUntilPosition.endsWith(' ');
        const word = model.getWordUntilPosition(position);

        const range: Monaco.IRange = {
          startLineNumber: position.lineNumber,
          endLineNumber: position.lineNumber,
          startColumn: hasDollar || hasDot || hasSpace ? position.column : word.startColumn,
          endColumn: position.column
        };

        const currentPath = getCurrentPath(textUntilPosition);
        const currentSuggestions = getSuggestionsForPath(currentPath, suggestions);

        return {
          suggestions: currentSuggestions.map((item, index) => {
            let insertText = item.label;

            const isLastLevel = !item.children || item.children.length === 0;
            const hasChildren = item.children && item.children.length > 0;

            const isOperator = item.detail && (
              item.detail.includes('Equal to') ||
              item.detail.includes('Not equal to') ||
              item.detail.includes('Greater than') ||
              item.detail.includes('Less than') ||
              item.detail.includes('Logical') ||
              item.detail.includes('Value in list') ||
              item.detail.includes('Identity comparison')
            );

            if (hasDot) {
              if (hasChildren) {
                insertText = `${insertText}.`;
              } else {
                insertText = `${insertText}}`;
              }
            } else if (hasBrace) {
              if (isLastLevel) {
                insertText = `${insertText}}`;
              } else {
                insertText = `${insertText}.`;
              }
            } else {
              if (isLastLevel) {
                insertText = isOperator ? insertText : `{${insertText}}`;
              } else {
                insertText = `{${insertText}.`;
              }
            }

            const suggestion: Monaco.languages.CompletionItem = {
              label: item.label,
              kind: monaco.languages.CompletionItemKind.Field,
              insertText: insertText,
              detail: item.detail || '',
              range: range,
              sortText: `${index}`.padStart(5, '0'),
              insertTextRules: monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet,
              command: hasChildren ? { id: 'editor.action.triggerSuggest', title: 'Trigger Suggest' } : undefined
            };
            return suggestion;
          })
        };
      }
    });
  }, [editorId, suggestions]);

  const handleEditorDidMount = (
    editor: Monaco.editor.IStandaloneCodeEditor,
    monaco: typeof Monaco
  ) => {
    editorRef.current = editor;
    monacoRef.current = monaco;

    registerCompletionProvider(monaco);

    editor.updateOptions({
      fontSize: 14,
      lineHeight: 20,
      quickSuggestions: {
        other: true,
        comments: true,
        strings: true
      },
      suggestOnTriggerCharacters: true,
      acceptSuggestionOnEnter: 'on',
      tabCompletion: 'on',
      wordBasedSuggestions: 'currentDocument',
      autoClosingBrackets: 'always',
      autoClosingQuotes: 'always',
      suggest: {
        showIcons: true,
        insertMode: 'insert',
        filterGraceful: true,
        snippetsPreventQuickSuggestions: false,
        localityBonus: true,
        shareSuggestSelections: true,
        showMethods: true,
        showFunctions: true,
        showVariables: true,
        showClasses: true,
        showWords: true,
        preview: true,
        previewMode: 'prefix',
        showInlineDetails: true
      }
    });

    monaco.editor.defineTheme('vs-gray', {
      base: 'vs',
      inherit: true,
      rules: [],
      colors: {
        'editor.background': '#f0f0f0',
      }
    });
    monaco.editor.setTheme('vs-gray');
  };

  useEffect(() => {
    if (monacoRef.current) {
      registerCompletionProvider(monacoRef.current);
    }
  }, [registerCompletionProvider]);

  useEffect(() => {
    return () => {
      if (providerRef.current) {
        providerRef.current.dispose();
      }
    };
  }, []);

  return (
    <Editor
      height={height}
      defaultLanguage={`markdown-${editorId}`}
      theme="vs-gray"
      value={value}
      onChange={onChange}
      onMount={handleEditorDidMount}
      options={{
        minimap: { enabled: false },
        lineNumbers: 'on',
        folding: false,
        wordWrap: 'on',
        contextmenu: false,
        scrollBeyondLastLine: false,
        automaticLayout: true,
        fontSize: 16,
        fontFamily: "'Menlo', 'Monaco', 'Courier New', monospace",
        lineHeight: 22,
        padding: { top: 10, bottom: 10 },
        renderLineHighlight: 'none',
        overviewRulerLanes: 0,
        hideCursorInOverviewRuler: true,
        overviewRulerBorder: false,
        quickSuggestions: true,
        suggestOnTriggerCharacters: true,
        acceptSuggestionOnEnter: 'on',
        tabCompletion: 'on',
        links: true,
        formatOnType: true
      }}
    />
  );
};

export default MonacoPromptEditor;
