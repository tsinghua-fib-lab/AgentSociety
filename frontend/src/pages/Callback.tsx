 
import { AuthCallback } from "../components/Auth";
import { sdkConfig } from "../components/authState";

const Callback = () => {
    return (
        <AuthCallback
            sdkConfig={sdkConfig}
            signinOrigin=""
            signinPath="/api/signin"
            onRedirect={() => {
                window.location.href = localStorage.getItem("backHref") ?? "/";
            }}
        />
    );
}

export default Callback;