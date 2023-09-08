////
////  ContentView.swift
////  hog
////
////  Created by Didi Hoffmann on 19.06.23.
////
//
//import SwiftUI
//import Charts
//import SQLite3
//import Cocoa
//import AppKit
//
//public func isScriptRunning(scriptName: String) -> Bool {
//    let process = Process()
//    let outputPipe = Pipe()
//    
//    process.launchPath = "/usr/bin/env"
//    process.arguments = ["pgrep", "-f", scriptName]
//    process.standardOutput = outputPipe
//    
//    do {
//        try process.run()
//        process.waitUntilExit()
//        
//        let outputData = outputPipe.fileHandleForReading.readDataToEndOfFile()
//        if let output = String(data: outputData, encoding: .utf8), !output.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
//            return true
//        }
//    } catch {
//        print("An error occurred: \(error)")
//    }
//    
//    return false
//}
//
//public func getNameByAppName(appName: String) -> String {
//    let runningApps = NSWorkspace.shared.runningApplications
//    for app in runningApps {
//        if app.bundleIdentifier == appName {
//            return app.localizedName ?? "No Data"
//        }
//    }
//    
//    let components = appName.split(separator: ".")
//    if let lastComponent = components.last {
//        return String(lastComponent)
//    }
//    
//    return "No Data"
//}
//
//public func getIconByAppName(appName: String) -> NSImage? {
//    let runningApps = NSWorkspace.shared.runningApplications
//    for app in runningApps {
//        if app.bundleIdentifier == appName {
//            return app.icon
//        }
//    }
//    return NSImage(systemSymbolName: "terminal", accessibilityDescription: nil)
//}
//
//
//class ValueManager: ObservableObject {
//    @Published var last5Min: CGFloat = 0
//    @Published var last24Hours: CGFloat = 0
//    @Published var totalEnergy: CGFloat = 0
//    @Published var providerRunning: Bool = false
//    @Published var top5MinApp: String = "Loading..."
//    @Published var top24HourApp: String = "Loading..."
//
//    enum ValueType {
//        case float
//        case string
//    }
//
//    
//    func fetchValues() {
//        DispatchQueue.global(qos: .userInitiated).async {
//            self.fetchValuesAsync()
//        }
//    }
//
//    func fetchValuesAsync() {
//        var db: OpaquePointer?
//
//        let fileManager = FileManager.default
//        let appSupportDir = fileManager.urls(for: .applicationSupportDirectory, in: .userDomainMask).first?.appendingPathComponent("gcb_hog")
//        
//        if let dir = appSupportDir {
//            let fileURL = dir.appendingPathComponent("db.db")
//            
//            if sqlite3_open(fileURL.path, &db) != SQLITE_OK { // Open database
//                print("error opening database")
//                return
//            }
//        } else {
//            print("Directory not found")
//            return
//        }
//        
//        var newLast5Min: CGFloat = 0
//        var newLast24Hours: CGFloat = 0
//        var newTotalEnergy: CGFloat = 0
//        var newTop5MinApp: String = "Loading"
//        var newTop24HourApp: String = "Loading"
//
//        let last5MinQuery = "SELECT COALESCE(sum(combined_energy), 0) FROM power_measurements WHERE time >= ((CAST(strftime('%s', 'now') AS INTEGER) * 1000) - 300000);"
//        if let result: CGFloat = queryDatabase(db: db, query:last5MinQuery, type: .float) {
//            newLast5Min = result
//        }
//
//
//        let last24HoursQuery = "SELECT COALESCE(sum(combined_energy), 0) FROM power_measurements WHERE time >= ((CAST(strftime('%s', 'now') AS INTEGER) * 1000) - 86400000);"
//        if let result: CGFloat = queryDatabase(db: db, query:last24HoursQuery, type: .float) {
//            newLast24Hours = result
//        }
//        
//        let totalEnergyQuery = "SELECT COALESCE(sum(combined_energy), 0) FROM power_measurements;"
//        if let result: CGFloat = queryDatabase(db: db, query:totalEnergyQuery, type: .float) {
//            newTotalEnergy = result
//        }
//        
//        
//        let top5MinAppQuery = """
//            SELECT name
//            FROM top_processes
//            WHERE time >= ((CAST(strftime('%s', 'now') AS INTEGER) * 1000) - 300000)
//            GROUP BY name
//            ORDER BY SUM(energy_impact) DESC
//            LIMIT 1; -- to get only the top name
//            """
//        
//        if let result: String = queryDatabase(db: db, query:top5MinAppQuery, type: .string) {
//            newTop5MinApp = String(result)
//        } else {
//            newTop5MinApp = "No data"
//        }
//        
//        let top24HourAppQuery = """
//            SELECT name
//            FROM top_processes
//            WHERE time >= ((CAST(strftime('%s', 'now') AS INTEGER) * 1000) - 86400000)
//            GROUP BY name
//            ORDER BY SUM(energy_impact) DESC
//            LIMIT 1; -- to get only the top name
//            """
//        
//        if let result: String = queryDatabase(db: db, query:top24HourAppQuery, type: .string) {
//            newTop24HourApp = String(result)
//        } else {
//            newTop5MinApp = "No data"
//        }
//
//        DispatchQueue.main.async {
//            self.last5Min = newLast5Min
//            self.totalEnergy = newTotalEnergy
//            self.last24Hours = newLast24Hours
//            self.providerRunning = isScriptRunning(scriptName: "power_logger_all.py")
//            self.top5MinApp = newTop5MinApp
//            self.top24HourApp = newTop24HourApp
//        }
//
//        sqlite3_close(db)
//
//    }
//
//
//    
//
//    private func queryDatabase<T>(db: OpaquePointer?, query: String, type: ValueType) -> T? {
//        var queryStatement: OpaquePointer?
//        
//        if sqlite3_prepare_v2(db, query, -1, &queryStatement, nil) == SQLITE_OK {
//            if sqlite3_step(queryStatement) == SQLITE_ROW {
//                switch type {
//                case .float:
//                    let value = CGFloat(sqlite3_column_double(queryStatement, 0))
//                    sqlite3_finalize(queryStatement)
//                    return value as? T
//                case .string:
//                    if let cString = sqlite3_column_text(queryStatement, 0) {
//                        let value = String(cString: cString)
//                        sqlite3_finalize(queryStatement)
//                        return value as? T
//                    }
//                }
//            }
//        }
//        sqlite3_finalize(queryStatement)
//        return nil
//    }
//}
//
//
//
//
//struct Home: View {
//    
//    @ObservedObject var valueManager = ValueManager()
//    @Environment(\.openWindow) private var openWindow
//    
//
//    
//    var body: some View {
//        VStack(spacing: 18) {
//            // MARK: TITLE
//            HStack {
//                VStack(alignment: .leading, spacing: 8) {
//                    Text("Quick Overview")
//                        .font(.title.bold())
//                }
//                
//                Spacer(minLength: 10)
//                Button(action: {
//                    valueManager.fetchValues()
//                }) {
//                    Image(systemName: "goforward")
//                }
//                Button(action: {
//                    exit(0)
//                }) {
//                    Image(systemName: "x.circle")
//                }
//
//
//            }
//            VStack() {
//                
//                HStack(spacing: 0) {
//                    ProcessBadge(title: "Highest energy\n 5 min", color: Color("chartColor2"), process: valueManager.top5MinApp)
//                    
//                    ProcessBadge(title: "Highest energy\n 24h", color: Color("chartColor2"),  process: valueManager.top24HourApp)
//                    
//                    
//                    if valueManager.providerRunning {
//                        TextBadge(title: "Running", color: Color("chartColor2"), image: "checkmark.seal", value: "Provider App")
//                    } else {
//                        TextBadge(title: "Not Running", color: Color("red"), image: "exclamationmark.octagon", value: "Provider App")
//                    }
//                    
//                }
//                HStack(spacing: 0) {
//                    EnergyBadge(title: "Last 5 Minutes", color: Color("chartColor2"), image: "clock.badge.checkmark", value: valueManager.last5Min, unit: "mJ")
//                    EnergyBadge(title: "Last 24 hours", color: Color("chartColor2"), image: "clock.badge.checkmark", value: valueManager.last24Hours, unit: "mJ")
//                    EnergyBadge(title: "Total System Energy", color: Color("chartColor2"), image: "bolt.circle", value: valueManager.totalEnergy, unit: "mJ")
//                }
//                
//            }
//            .padding()
//            .cornerRadius(18)
//
//            Button("View more details") {
//                openWindow(id: "details")
//            }
//
//                        
//        }
//        .onAppear {
//            valueManager.fetchValues()
//        }.padding()
//    }
//    
//    @ViewBuilder
//    func ProcessBadge(title: String, color: Color, process: String)->some View {
//        HStack {
//            Image(nsImage: getIconByAppName(appName: process) ?? NSImage())
//                .font(.title2)
//                .foregroundColor(color)
//                .padding(10)
//            
//            VStack(alignment: .leading, spacing: 8) {
//                Text(title)
//                    .font(.caption2.bold())
//                    .foregroundColor(.gray)
//
//                Text(getNameByAppName(appName: process))
//                    .font(.title2.bold())
//
//            }
//        }
//        .frame(maxWidth: .infinity, alignment: .leading)
//    }
//
//    @ViewBuilder
//    func EnergyBadge(title: String, color: Color, image: String, value: CGFloat, unit: String)->some View {
//        HStack {
//            Image(systemName: image)
//                .font(.title2)
//                .foregroundColor(color)
//                .padding(10)
//            
//            VStack(alignment: .leading, spacing: 8) {
//                Text(String(format: "%.1f %@", value  / 1000, unit))
//                    .font(.title2.bold())
//
//                Text(title)
//                    .font(.caption2.bold())
//                    .foregroundColor(.gray)
//            }
//        }
//        .frame(maxWidth: .infinity, alignment: .leading)
//    }
//    @ViewBuilder
//    func TextBadge(title: String, color: Color, image: String, value: String)->some View {
//        HStack {
//            Image(systemName: image)
//                .font(.title2)
//                .foregroundColor(color)
//                .padding(10)
//            
//            VStack(alignment: .leading, spacing: 8) {
//                Text(value)
//                    .font(.title2.bold())
//
//                Text(title)
//                    .font(.caption2.bold())
//                    .foregroundColor(.gray)
//            }
//        }
//        .frame(maxWidth: .infinity, alignment: .leading)
//    }
//}
//
//
//
//struct ContentView: View {
//    var body: some View{
//        Home()
//    }
//}
//
//
//
//struct ContentView_Previews: PreviewProvider {
//    static var previews: some View {
//        ContentView()
//    }
//}
