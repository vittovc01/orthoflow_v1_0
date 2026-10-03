# OrthoFlow branding

Every page configuration uses `orthoflow_branding.configure_page`: existing titles and layouts are preserved; the browser favicon and sidebar/header logo use the local OrthoFlow assets. Keep new pages on this helper.

`client.toolbarMode="minimal"` limits host controls. Narrow CSS hides only ToolbarActions (Fork/GitHub), DeployButton, MainMenu and the Streamlit viewer badge. Never hide stToolbar or stAppToolbar: the mobile Expand sidebar button is a descendant of that container in current Streamlit. Both the header and full toolbar stay available for the product logo and sidebar toggle. CSS selectors may need adjustment after Streamlit frontend changes.

Verification before declaring the hosted UI complete:
- Open login, Control Tower, Scarico Sala AI, DDT and Controllo di Gestione on desktop and mobile.
- Confirm the custom favicon/logo, absent Fork/GitHub controls and absent viewer badge.
- Close and reopen the sidebar on a narrow screen.
- Verify page actions, logout and downloads.

This change does not create an installable PWA or a native app. Safari Home Screen icons may use the hosting document's apple-touch-icon independently of the dynamic browser favicon; the existing saved Streamlit icon has not been verified as replaced. A branded installable deployment needs control of the served document head, Apple touch icon and web app manifest, plus authentication and WebSocket routing. Do not claim that replacing the favicon alone completes iPhone installation.
