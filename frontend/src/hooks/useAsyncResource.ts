import { useCallback, useEffect, useRef, useState } from 'react';

/** Load on mount and refresh on demand; only the latest request may update state. */
export function useAsyncResource<T>(
    load: () => Promise<T>,
    onError: (error: unknown) => void,
    initialValue: T,
) {
    const [data, setData] = useState(initialValue);
    const [loading, setLoading] = useState(true);
    const requestId = useRef<symbol | null>(null);

    useEffect(() => {
        const id = Symbol();
        requestId.current = id;
        load().then(
            value => { if (id === requestId.current) setData(value); },
            error => { if (id === requestId.current) onError(error); },
        ).finally(() => {
            if (id === requestId.current) setLoading(false);
        });
        return () => { requestId.current = null; };
    }, [load, onError]);

    const reload = useCallback(async () => {
        const id = Symbol();
        requestId.current = id;
        setLoading(true);
        try {
            const value = await load();
            if (id === requestId.current) setData(value);
        } catch (error) {
            if (id === requestId.current) onError(error);
        } finally {
            if (id === requestId.current) setLoading(false);
        }
    }, [load, onError]);

    return { data, loading, reload };
}
