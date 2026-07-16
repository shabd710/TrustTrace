/**
 * Expo entry registration.
 *
 * Spec ref: Target Environment (React Native / Expo bare workflow). This
 * is the entry Expo's Metro bundler resolves. `registerRootComponent`
 * wraps App and calls AppRegistry.registerComponent, which is what was
 * missing — hence the "Unable to resolve ../../App from
 * node_modules/expo/AppEntry.js" failure. With this file present and
 * referenced as `main` in package.json, Expo loads App.tsx directly and
 * no longer falls back to AppEntry.js's hardcoded ../../App path.
 */
import { registerRootComponent } from "expo";
import App from "./App";

registerRootComponent(App);
