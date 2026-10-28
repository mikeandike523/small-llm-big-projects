// Which folder picker the New Session dialog uses.
//
// "native": inside the desktop app, whose tab preload exposes
//   window.slbpDesktop. The desktop app always runs its own local server, so
//   the OS folder dialog shows the server's filesystem.
// "remote": any normal browser (e.g. a production server reached over the
//   network) -- an in-page widget that browses the server's filesystem.
//
// Electron runs the preload before any page script, so this is already final
// when the bundle loads: no async check or loading state is needed.
export type FolderPickerMode = "native" | "remote";

export const FOLDER_PICKER_MODE: FolderPickerMode =
  typeof window !== "undefined" &&
  typeof window.slbpDesktop?.pickFolder === "function"
    ? "native"
    : "remote";
