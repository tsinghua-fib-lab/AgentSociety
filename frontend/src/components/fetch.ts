import { t } from "i18next";
import { getAccessToken } from "./Auth";
import { message } from "antd";

export const WITH_AUTH = import.meta.env.VITE_WITH_AUTH === 'true';

export const fetchWithAuth = async (url: string, options: RequestInit = {}) => {
    const token = getAccessToken();
    if (!token) {
        throw new Error("No token found, please login");
    }
    options.headers = { ...options.headers, Authorization: `Bearer ${token}` };
    return fetch(url, options);
}

export const fetchCustom = async (url: string, options: RequestInit = {}) => {
    if (WITH_AUTH) {
        return fetchWithAuth(url, options);
    }
    return fetch(url, options);
};

export const postDownload = async (url: string) => {
    const form = document.createElement('form');
    form.action = url;
    form.method = 'POST';
    form.target = '_blank';
    document.body.appendChild(form);
    form.submit();
    document.body.removeChild(form);
}

export const postDownloadWithAuth = async (url: string) => {
    const token = getAccessToken();
    if (!token) {
        message.error(t('console.messages.noToken'));
        return;
    }
    const authorization = `Bearer ${token}`;
    const form = document.createElement('form');
    form.action = url;
    form.method = 'POST';
    form.target = '_blank';
    const input = document.createElement('input');
    input.type = 'hidden';
    input.name = 'authorization';
    input.value = authorization;
    form.appendChild(input);
    document.body.appendChild(form);
    form.submit();
    document.body.removeChild(form);
}

export const postDownloadCustom = async (url: string) => {
    if (WITH_AUTH) {
        return postDownloadWithAuth(url);
    }
    return postDownload(url);
}
