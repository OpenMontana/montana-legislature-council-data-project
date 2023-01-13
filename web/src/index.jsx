import React from "react";
import ReactDOM from "react-dom";
import { App, AppConfigProvider } from "@openmontana/cdp-frontend";

import "@openmontana/cdp-frontend/dist/index.css";

const config = {
    firebaseConfig: {
        options: {
            projectId: "cdp-montana-legislature",
        },
        settings: {},
    },
    municipality: {
        name: "Montana State Legislature",
        timeZone: "America/Denver",
        footerLinksSections: [],
    },
}

ReactDOM.render(
    <div>
        <AppConfigProvider appConfig={config}>
            <App />
        </AppConfigProvider>
    </div>,
    document.getElementById("root")
);
