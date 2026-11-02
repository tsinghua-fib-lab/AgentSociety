import { createContext, useContext } from "react";
import { jwtDecode, type JwtPayload } from "jwt-decode";
import Sdk from "casdoor-js-sdk";
import type { SdkConfig } from "casdoor-js-sdk/lib/esm/sdk";

export const sdkConfig = {
    serverUrl: "https://login.fiblab.net",
    clientId: "7ffcbfe4ae0fcb2c0d63",
    appName: "agentsociety",
    organizationName: "fiblab",
    redirectPath: "/callback",
    signinPath: "/api/signin",
};

export const DEMO_USER_TOKEN = "DEMO_USER_TOKEN";

let casdoorSdk: Sdk | undefined;

/** 获取全局的 Casdoor SDK，如果还没有初始化，就用 `config` 新建一个。*/
export function getCasdoorSdk(config: SdkConfig) {
    return (casdoorSdk ??= new Sdk(config));
}

/** 获取全局的 access token。未登录时返回 `null`。*/
export function getAccessToken() {
    const token = localStorage.getItem("access_token");
    if (token === DEMO_USER_TOKEN) {
        return token;
    }
    // 检查 token 是否过期
    if (token) {
        const decoded = jwtDecode<AccessTokenPayload>(token);
        if (decoded.exp < Date.now() / 1000) {
            localStorage.removeItem("access_token");
            return null;
        }
    }
    return token;
}

export interface AccessTokenPayload extends JwtPayload {
    /**
     * Token 的发布者。见 [JWT 标准][1]。
     *
     * [1]: https://datatracker.ietf.org/doc/html/rfc7519#section-4.1
     */
    iss: string;
    /**
     * Token 的主题。见 [JWT 标准][1]。
     *
     * [1]: https://datatracker.ietf.org/doc/html/rfc7519#section-4.1
     */
    sub: string;
    /**
     * Token 的目标应用 ID。见 [JWT 标准][1]。
     *
     * [1]: https://datatracker.ietf.org/doc/html/rfc7519#section-4.1
     */
    aud: string[];
    /**
     * 使用 Token 的应用 ID。见 [JWT 标准][1]。
     *
     * [1]: https://datatracker.ietf.org/doc/html/rfc7519#section-4.1
     */
    azp: string;
    /**
     * Token 的唯一标识符。见 [JWT 标准][1]。
     *
     * [1]: https://datatracker.ietf.org/doc/html/rfc7519#section-4.1
     */
    jti: string;
    /** Token 的过期时间（Unix 时间戳）。*/
    exp: number;
    /** Token 的生效时间（Unix 时间戳）。*/
    nbf: number;
    /** Token 的签发时间（Unix 时间戳）。*/
    iat: number;

    /** 用户的登录名。*/
    name: string;
    /** 用户的 UUID。*/
    id: string;
    /** 用户的显示名。*/
    displayName: string;
    /** 用户的头像 URL。*/
    avatar: string;
    /** 用户的邮件地址。*/
    email: string;
    /** 用户的手机号。*/
    phone: string;

    owner: "fiblab";
    tokenType: "access-token";
    scope: "profile";
}

/** 获取全局的 access token 并解码。解码得到的 payload 中也有一些用户信息，
 * 可以在一定程度上代替通过 API 获取用户信息。未登录时返回 `null`。*/
export function getDecodedAccessToken() {
    const token = getAccessToken();
    if (token === null) return;
    return jwtDecode<AccessTokenPayload>(token);
}

export interface UserInfo {
    /**
     * Token 的发布者。见 [JWT 标准][1]。
     *
     * [1]: https://datatracker.ietf.org/doc/html/rfc7519#section-4.1
     */
    iss: string;
    /**
     * Token 的主题。见 [JWT 标准][1]。
     *
     * [1]: https://datatracker.ietf.org/doc/html/rfc7519#section-4.1
     */
    sub: string;
    /**
     * Token 的目标应用 ID。见 [JWT 标准][1]。
     *
     * [1]: https://datatracker.ietf.org/doc/html/rfc7519#section-4.1
     */
    aud: string;
    /** 用户的全名（显示名）。*/
    name: string;
    /** 短用户名（登录名）。*/
    prefered_username: string;
    /** 用户的邮件地址。*/
    email?: string;
    /** 用户的邮件地址是否已确认。*/
    email_verified?: boolean;
    /** 用户的手机号。*/
    phone?: string;
    /** 用户的头像 URL。*/
    picture: string;
    /** 用户的地址。*/
    address?: string;
    /** 用户所属的用户组。*/
    groups: string[];
    /** 用户的角色。*/
    roles: string[];
}

export const AuthContext = createContext<UserInfo | undefined>(undefined);

/** 获取用户信息。必须在开启了 `onlineCheck` 的 {@linkcode AuthProvider} 内部使用，否则返回 `undefined`。*/
export function useUserInfo() {
    return useContext(AuthContext);
}
