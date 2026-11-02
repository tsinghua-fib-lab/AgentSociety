import { type ReactNode, useEffect, useState } from "react";
import type { SdkConfig } from "casdoor-js-sdk/lib/esm/sdk";
import { AuthContext, getAccessToken, getCasdoorSdk, type UserInfo } from "./authState";

export interface AuthProviderProps {
    /**
     * Casdoor SDK 的配置。
     *
     * **注意**：初始化的 SDK 将保存为全局变量，因此一个项目内不可有多个不同的 SDK 配置。
     * 通过 {@linkcode getCasdoorSdk} 可以获取到全局的 SDK。
     */
    sdkConfig: SdkConfig;
    /**
     * 是否联网检查用户登录状态有效性。如果检查，那么在内部还可以使用 {@linkcode useUserInfo} 访问到用户信息。
     * @default false
     */
    onlineCheck?: boolean;
    /**
     * 如果开启了 `onlineCheck`，在检查过程中时向用户显示的加载界面。
     * @default "Logging in……"
     */
    loading?: ReactNode;
    /** 用户登录后显示的内容。*/
    children: ReactNode;
    /**
     * 是否立即跳转到登录页面。
     * @default true
     */
    gotoLoginImmediately?: boolean;
}

/**
 * 确保只有已登录的用户可以访问到内部的内容，未登录的用户将被重定向到登录界面。
 */
export function AuthProvider(props: AuthProviderProps): ReactNode {
    const sdk = getCasdoorSdk(props.sdkConfig);
    const token = getAccessToken();
    const [userInfo, setUserInfo] = useState<UserInfo>();
    useEffect(
        () => {
            if (token === null) {
                if (props.gotoLoginImmediately === true || props.gotoLoginImmediately === undefined) {
                    location.href = sdk.getSigninUrl();
                }
            } else {
                if (props.onlineCheck) {
                    sdk.getUserInfo(token).then((_resp) => {
                        // sdk 的类型声明有误
                        const resp = _resp as unknown as UserInfo | { status: "error" };
                        if ("status" in resp) {
                            location.href = sdk.getSigninUrl();
                        } else {
                            setUserInfo(resp);
                        }
                    });
                }
            }
        },
        [token, props.onlineCheck], // eslint-disable-line react-hooks/exhaustive-deps
    );
    if (props.gotoLoginImmediately === false) {
        return (
            <AuthContext.Provider value={userInfo}>
                {props.children}
            </AuthContext.Provider>
        );
    }
    return token === null ? (
        "Skipping login……"
    ) : props.onlineCheck && userInfo === undefined ? (
        (props.loading ?? "Logging in……")
    ) : (
        <AuthContext.Provider value= { userInfo } >
        { props.children }
    </AuthContext.Provider>
  );
}

export interface AuthCallbackProps {
    /**
     * Casdoor SDK 的配置。
     *
     * **注意**：初始化的 SDK 将保存为全局变量，因此一个项目内不可有多个不同的 SDK 配置。
     * 通过 {@linkcode getCasdoorSdk} 可以获取到全局的 SDK。
     */
    sdkConfig: SdkConfig;
    /** 登录的 API 源点，末尾不带 `/`。*/
    signinOrigin: string;
    /**
     * 登陆的 API 路径。
     * @default "/api/signin"
     */
    signinPath?: string;
    /**
     * 跳转时的回调。可以使用 React Router 的跳转函数。
     * @default () => { location.href = "/"; }
     */
    onRedirect?: () => void;
    /**
     * 发生错误时显示的内容。
     * @default (err) => err.toString()
     */
    error?: (err: unknown) => ReactNode;
    /**
     * 跳转前显示的内容。
     * @default "Skipping login……"
     */
    children?: ReactNode;
}

/** 登录的回调页面。*/
export function AuthCallback(props: AuthCallbackProps): ReactNode {
    const [error, setError] = useState<unknown>();
    useEffect(
        () => {
            getCasdoorSdk(props.sdkConfig)
                .signin(props.signinOrigin, props.signinPath)
                .then((_resp) => {
                    // sdk 的类型声明有误
                    const resp = _resp as unknown as { token?: string };
                    if (!resp.token) {
                        throw new Error(
                            "Login API returned an abnormal result: " + JSON.stringify(resp),
                        );
                    }
                    localStorage.setItem("access_token", resp.token);
                    if (props.onRedirect) {
                        props.onRedirect();
                    } else {
                        location.href = "/";
                    }
                })
                .catch((err) => setError(err));
        },
        [], // eslint-disable-line react-hooks/exhaustive-deps
    );
    return error
        ? props.error
            ? props.error(error)
            : (error as object).toString()
        : (props.children ?? "Skipping login……");
}
