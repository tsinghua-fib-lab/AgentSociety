import * as React from 'react';
import { Alert } from 'antd';
import type { TFunction } from 'i18next';
import type { VscodeThemePalette } from '../theme';
import type { ValidationState } from './types';
import { ValidationAction } from './ValidationAction';
import { tabBodyStyle } from './configPageStyles';

type Props = {
  t: TFunction;
  palette: VscodeThemePalette;
  validationState: ValidationState;
  disabledReason: string | null;
  onValidate: () => void;
  sectionRef: React.RefObject<HTMLDivElement | null>;
  children: React.ReactNode;
  showIntro?: boolean;
};

export function LiteratureConfigSection({
  t,
  palette,
  validationState,
  disabledReason,
  onValidate,
  sectionRef,
  children,
  showIntro = true,
}: Props) {
  return (
    <div ref={sectionRef} style={tabBodyStyle}>
      {showIntro ? (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 14 }}
          message={t('configPage.pageTabs.literatureIntroTitle')}
          description={t('configPage.pageTabs.literatureIntroBody')}
        />
      ) : null}
      {children}
      <div style={{ marginTop: 12 }}>
        <ValidationAction
          t={t}
          palette={palette}
          state={validationState}
          disabledReason={disabledReason}
          onValidate={onValidate}
          label={t('configPage.literature.validateConfig')}
          size="small"
          primary={false}
        />
      </div>
    </div>
  );
}
