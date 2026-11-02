import React, { Suspense, lazy } from 'react'
import { Navigate, createBrowserRouter } from 'react-router'
import { RouterProvider } from 'react-router/dom'
import { ConfigProvider, Spin, ThemeConfig } from 'antd'
import RootLayout from './Layout'
import Home from './pages/Home'
import zhCN from 'antd/locale/zh_CN'
import enUS from 'antd/locale/en_US'
import Callback from './pages/Callback'
import { AuthProvider } from './components/Auth'
import { sdkConfig } from './components/authState'
import { useTranslation } from 'react-i18next'
import { WITH_AUTH } from './components/fetch'

const Console = lazy(() => import('./pages/Console/index'))
const Replay = lazy(() => import('./pages/Replay/index'))
const Survey = lazy(() => import('./pages/Survey/index'))
const LLM = lazy(() => import('./pages/LLM'))
const AgentList = lazy(() => import('./pages/Agent/'))
const WorkflowList = lazy(() => import('./pages/Workflow'))
const Map = lazy(() => import('./pages/Map'))
const CreateExperiment = lazy(() => import('./pages/Experiment/CreateExperiment'))
const ProfileList = lazy(() => import('./pages/AgentProfile'))
const AgentTemplate = lazy(() => import('./pages/AgentTemplate/AgentTemplateList'))
const Bill = lazy(() => import('./pages/Bill'))
const AgentTemplateForm = lazy(() => import('./pages/AgentTemplate/AgentTemplateForm'))
const Skills = lazy(() => import('./pages/Skills'))

const routeFallback = (
    <div style={{ display: 'flex', justifyContent: 'center', padding: 48 }}>
        <Spin size="large" />
    </div>
)

const withSuspense = (node: React.ReactNode) => (
    <Suspense fallback={routeFallback}>{node}</Suspense>
)

const authProvider = (children: React.ReactNode) => {
    if (WITH_AUTH) {
        return (
            <AuthProvider sdkConfig={sdkConfig}>
                {children}
            </AuthProvider>
        )
    }
    return children;
}

const router = createBrowserRouter([
    {
        path: "/",
        element: <RootLayout selectedKey='/' homePage><Home /></RootLayout>,
    },
    {
        path: "/console",
        element: (
            authProvider(
                <RootLayout selectedKey='/console'>{withSuspense(<Console />)}</RootLayout>
            )
        ),
    },
    {
        path: "/exp/:id",
        element: (
            authProvider(
                <RootLayout selectedKey='/console'>{withSuspense(<Replay />)}</RootLayout>
            )
        ),
    },
    {
        path: "/survey",
        element: (
            authProvider(
                <RootLayout selectedKey='/survey'>{withSuspense(<Survey />)}</RootLayout>
            )
        ),
    },
    {
        path: "/create-experiment",
        element: (
            authProvider(
                <RootLayout selectedKey='/create-experiment'>{withSuspense(<CreateExperiment />)}</RootLayout>
            )
        ),
    },
    {
        path: "/llms",
        element: (
            authProvider(
                <RootLayout selectedKey='/llms'>{withSuspense(<LLM />)}</RootLayout>
            )
        ),
    },
    {
        path: "/agents",
        element: (
            authProvider(
                <RootLayout selectedKey='/agents'>{withSuspense(<AgentList />)}</RootLayout>
            )
        ),
    },
    {
        path: "/profiles",
        element: (
            authProvider(
                <RootLayout selectedKey='/profiles'>{withSuspense(<ProfileList />)}</RootLayout>
            )
        ),
    },
    {
        path: "/workflows",
        element: (
            authProvider(
                <RootLayout selectedKey='/workflows'>{withSuspense(<WorkflowList />)}</RootLayout>
            )
        ),
    },
    {
        path: "/maps",
        element: (
            authProvider(
                <RootLayout selectedKey='/maps'>{withSuspense(<Map />)}</RootLayout>
            )
        ),
    },
    {
        path: "/bill",
        element: (
            authProvider(
                <RootLayout selectedKey='/bill'>{withSuspense(<Bill />)}</RootLayout>
            )
        ),
    },
    {
        path: "/callback",
        element: <Callback />,
    },
    {
        path: "/agent-templates",
        element: (
            authProvider(
                <RootLayout selectedKey='/agent-templates'>{withSuspense(<AgentTemplate />)}</RootLayout>
            )
        ),
    },
    {
        path: "/agent-templates/create",
        element: (
            authProvider(
                <RootLayout selectedKey='/agent-templates'>{withSuspense(<AgentTemplateForm />)}</RootLayout>
            )
        ),
    },
    {
        path: "/agent-templates/edit/:id",
        element: (
            authProvider(
                <RootLayout selectedKey='/agent-templates'>{withSuspense(<AgentTemplateForm />)}</RootLayout>
            )
        ),
    },
    {
        path: "/skills",
        element: (
            authProvider(
                <RootLayout selectedKey='/skills'>{withSuspense(<Skills />)}</RootLayout>
            )
        ),
    },
    {
        path: "*",
        element: <Navigate to="/" />,
    }
])

const theme: ThemeConfig = {
    token: {
        colorPrimary: "#0000CC",
        colorInfo: "#0000CC",
        borderRadius: 16,
        colorBgContainer: "#FFFFFF",
        colorBgLayout: "#FFFFFF",
    },
    components: {
        Layout: {
            lightSiderBg: "#F8F8F8",
            headerBg: "#FFFFFF",
        },
        Button: {
            algorithm: true,
            colorBgContainer: "#FFFFFF",
        },
        Select: {
            colorBgContainer: "#FFFFFF",
        }
    }
};

const App = () => {
    const { i18n } = useTranslation()

    return (
        <ConfigProvider
            theme={theme}
            locale={i18n.language === 'en' ? enUS : zhCN}
        >
            <RouterProvider router={router} />
        </ConfigProvider>
    )
}

export default App
