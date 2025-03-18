//
//  SettingsView.swift
//  hog
//
//  Created by Didi Hoffmann on 18.10.23.
//

import SwiftUI
import SQLite3
import Charts
import AppKit
import Foundation


func createLaunchAgent() {

    guard let bundleIdentifier = Bundle.main.bundleIdentifier else {
        print("No bundle identifier found.")
        return
    }

    guard let executablePath = Bundle.main.executableURL?.path else {
           print("No executable path found.")
           return
    }

    let launchAgentsURL = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent("Library/LaunchAgents", isDirectory: true)

    let plistURL = launchAgentsURL.appendingPathComponent("\(bundleIdentifier).plist")

    let plist: [String: Any] = [
        "Label": bundleIdentifier as Any,
        "ProgramArguments": [executablePath],
        "RunAtLoad": false,
        "KeepAlive": false,
        "LimitLoadToSessionType": "Aqua"
    ]

    do {
        let xmlData = try PropertyListSerialization.data(fromPropertyList: plist, format: .xml, options: 0)
        try FileManager.default.createDirectory(at: launchAgentsURL, withIntermediateDirectories: true, attributes: nil)
        try xmlData.write(to: plistURL)
    } catch {
        print("Failed to create launch agent: \(error)")
    }



    let task = Process()
    task.launchPath = "/bin/bash"
    task.arguments = ["-c", "launchctl bootstrap gui/`id -u` \(plistURL.path())"]
    task.launch()
    task.waitUntilExit()
}

func removeLaunchAgent() {
    guard let bundleIdentifier = Bundle.main.bundleIdentifier else {
        print("No bundle identifier found.")
        return
    }

    let launchAgentsURL = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent("Library/LaunchAgents", isDirectory: true)

    let plistURL = launchAgentsURL.appendingPathComponent("\(bundleIdentifier).plist")

    guard FileManager.default.fileExists(atPath: plistURL.path) else {
        print("No Launch Agent to remove at \(plistURL.path())")
        return
    }

    let unloadTask = Process()
    unloadTask.launchPath = "/bin/bash"
    unloadTask.arguments = ["-c", "launchctl bootout gui/`id -u` \(plistURL.path())"]
    unloadTask.launch()
    unloadTask.waitUntilExit()

    do {
        try FileManager.default.removeItem(at: plistURL)
        print("Launch Agent removed successfully.")
    } catch {
        print("Failed to remove Launch Agent: \(error)")
    }
}

func isLaunchAgentInstalled() -> Bool {
    guard let bundleIdentifier = Bundle.main.bundleIdentifier else {
        return false
    }
    let launchAgentsURL = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent("Library/LaunchAgents", isDirectory: true)
    let plistURL = launchAgentsURL.appendingPathComponent("\(bundleIdentifier).plist")
    return FileManager.default.fileExists(atPath: plistURL.path)
}


class SettingsManager: ObservableObject {

    @Published var machine_uuid: String = "Loading ..."
    @Published var powermetrics: Int = 0
    @Published var api_url: String = "Loading ..."
    @Published var web_url: String = "Loading ..."
    @Published var upload_data: Bool = true

    @Published var upload_backlog: Int = 0

    @Published var isLoading: Bool = false


    init(){
        self.isLoading = true

        DispatchQueue.global(qos: .userInitiated).async {
            self.loadDataFrom()
            DispatchQueue.main.async {
                self.isLoading = false
            }
        }
    }

    func loadDataFrom() {
        var db: OpaquePointer?

        if sqlite3_open(db_path, &db) != SQLITE_OK { // Open database
            print("error opening database")
            return
        }

        let lastMeasurementQuery = "SELECT machine_uuid, powermetrics, api_url, web_url, upload_data FROM settings ORDER BY time DESC LIMIT 1;"
        var queryStatement: OpaquePointer?

        var new_machine_uuid = "Loading ..."
        var new_powermetrics: Int = 0
        var new_api_url = "Loading ..."
        var new_web_url = "Loading ..."
        var upload_data = true

        if sqlite3_prepare_v2(db, lastMeasurementQuery, -1, &queryStatement, nil) == SQLITE_OK {
            if sqlite3_step(queryStatement) == SQLITE_ROW {
                new_machine_uuid = String(cString: sqlite3_column_text(queryStatement, 0))
                new_powermetrics = Int(sqlite3_column_int(queryStatement, 1))
                new_api_url = String(cString: sqlite3_column_text(queryStatement, 2))
                new_web_url = String(cString: sqlite3_column_text(queryStatement, 3))
                upload_data = sqlite3_column_int(queryStatement, 4) != 0 // assuming it's stored as 0 for false, non-0 for true
            }
            sqlite3_finalize(queryStatement)
        }

        let uploadCountQuery = "SELECT COUNT(*) FROM measurements WHERE uploaded = 0;"
        var new_upload_backlog: Int = 0

        if sqlite3_prepare_v2(db, uploadCountQuery, -1, &queryStatement, nil) == SQLITE_OK {
            if sqlite3_step(queryStatement) == SQLITE_ROW {
                new_upload_backlog = Int(sqlite3_column_int(queryStatement, 0))
            }
            sqlite3_finalize(queryStatement) // Always finalize your statement when done
        } else {
            print("SELECT statement could not be prepared")
        }

        sqlite3_close(db)

        DispatchQueue.main.async {
            self.machine_uuid = new_machine_uuid
            self.powermetrics = new_powermetrics
            self.api_url = new_api_url
            self.web_url = new_web_url
            self.upload_data = upload_data
            self.upload_backlog = new_upload_backlog
        }

    }

}

private struct SettingDetailView: View {
    let title: String
    let value: String

    var body: some View {
        Group {
            Text(title)
                .bold()
            Text(value)
                .padding(.bottom, 10)
        }
    }
}


struct SettingsView: View {

    @ObservedObject var settingsManager = SettingsManager()
    var viewModel: ViewModel
    var whoAmI: TabSelection

    init(viewModel: ViewModel, whoAmI: TabSelection){
        self.viewModel = viewModel
        self.whoAmI = whoAmI
    }

    var body: some View {
        VStack(alignment: .leading) {
            HStack {
                VStack(alignment: .leading, spacing: 8) {
                    Text("Settings")
                        .font(.headline)
                        .bold()
                }

                Spacer(minLength: 10)

                Button(action: {
                    self.settingsManager.loadDataFrom()
                }) {
                    Image(systemName: "goforward")
                }
                Button(action: {
                    exit(0)
                }) {
                    Image(systemName: "x.circle")
                }

            }

            if settingsManager.isLoading {
                Text("Loading")
            } else {
                Text("These are the settings that are set by the power logger.\nPlease refer to https://github.com/green-coding-solutions/hog#settings")
                Divider().padding()
                SettingDetailView(title: "Machine ID:", value: settingsManager.machine_uuid)
                SettingDetailView(title: "Powermetrics Intervall:", value: "\(settingsManager.powermetrics)")
                SettingDetailView(title: "Upload to URL:", value: settingsManager.api_url)
                SettingDetailView(title: "Web View URL:", value: settingsManager.web_url)
                SettingDetailView(title: "Upload data:", value: settingsManager.upload_data ? "Yes" : "No")
                SettingDetailView(title: "Upload Backlog Count:", value: "\(settingsManager.upload_backlog)")
            }

        }
        .padding()
        .onReceive(viewModel.$selectedTab) { tab in
            if tab == self.whoAmI {
                self.settingsManager.loadDataFrom()
            }
        }

    }
}
