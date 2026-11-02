import { useMemo } from 'react';
import { Model } from 'survey-core';
import { Survey } from 'survey-react-ui';

export default function SurveyPreviewRenderer({ value }: { value?: string }) {
    const model = useMemo(() => {
        let data = {};
        try {
            data = JSON.parse(value || '{}');
        } catch (error) {
            console.error('Failed to parse survey:', error);
        }
        const model = new Model(data);
        model.showCompleteButton = false;
        return model;
    }, [value]);
    return <Survey model={model} />;
}
