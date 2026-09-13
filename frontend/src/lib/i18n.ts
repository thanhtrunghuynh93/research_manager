import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import en from "@/locales/en/common.json";

/**
 * One language. Strings still resolve through i18next rather than being inlined in the
 * components, so adding a second is a resource entry and a switcher — but nothing in the UI
 * offers a choice, and nothing reads a stored preference.
 */
void i18n.use(initReactI18next).init({
  resources: { en: { common: en } },
  lng: "en",
  fallbackLng: "en",
  defaultNS: "common",
  interpolation: { escapeValue: false },
});

export default i18n;
