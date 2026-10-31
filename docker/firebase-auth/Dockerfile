# Local test only (branch pai-merge): the Firebase Auth emulator, so sign-in never touches a real
# Firebase project. The Auth emulator is plain Node (Java is only needed for other emulators).
# Project id "demo-pai-merge": a "demo-" id is offline-only by Firebase's rules, so even a mistake
# cannot reach a real project.
FROM node:20-bookworm-slim
ENV NPM_CONFIG_UPDATE_NOTIFIER=false \
    FIREBASE_CLI_DISABLE_UPDATE_CHECK=true
RUN npm install -g --no-audit --no-fund firebase-tools@13.35.1 \
    # Download the emulator web UI now, so the container needs no internet at start.
    && firebase setup:emulators:ui
WORKDIR /emulator
COPY firebase.json .firebaserc ./
# Auth emulator on 9099, its web UI (list of test users) on 4000. Test users are kept across
# restarts: exported on a clean stop, imported on start. The export goes into a sub-folder of
# the volume at /emulator/store (the emulator replaces the export folder, which it cannot do
# to a volume's mount point).
EXPOSE 9099 4000
CMD ["firebase", "emulators:start", "--only", "auth", "--project", "demo-pai-merge", \
     "--import", "/emulator/store/auth-export", "--export-on-exit", "/emulator/store/auth-export"]
