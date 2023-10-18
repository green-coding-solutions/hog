//
//  DetailView.swift
//  hog
//
//  Created by Didi Hoffmann <didi@green-coding.berlin>
//
// A few things to note:
// - We can not share the db pointer for the whole app as sqlite does not allow multiple threads to share one connection
// - Getting the data needs to be in single threads as otherwise the front end might lock up
//

import SwiftUI
import SQLite3
import Charts
import AppKit
import Combine

var db_path = "/Library/Application Support/berlin.green-coding.hog/db.db"


public func isScriptRunning(scriptName: String) -> Bool {
    if isAppSandboxed() {
        return isScriptRunningUsingDBCheck()
    } else {
        return isScriptRunningUsingPGrep(scriptName: scriptName)
    }
}

func isAppSandboxed() -> Bool {
    let bundleIdentifier = Bundle.main.bundleIdentifier ?? ""
    let containerURL = FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: bundleIdentifier)
    return containerURL != nil
}


private func isScriptRunningUsingPGrep(scriptName: String) -> Bool {
    let process = Process()
    let outputPipe = Pipe()

    process.launchPath = "/usr/bin/env"
    process.arguments = ["pgrep", "-f", scriptName]
    process.standardOutput = outputPipe

    do {
        try process.run()
        process.waitUntilExit()

        let outputData = outputPipe.fileHandleForReading.readDataToEndOfFile()
        if let output = String(data: outputData, encoding: .utf8), !output.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            return true
        }
    } catch {
        print("Error checking script using pgrep: \(error)")
    }

    return false
}

private func isScriptRunningUsingDBCheck() -> Bool {
    var db: OpaquePointer?
    var running = false

    if sqlite3_open(db_path, &db) != SQLITE_OK {
        print("error opening database")
        return false
    }

    var queryStatement: OpaquePointer?

    let queryString = "SELECT COUNT (*) FROM power_measurements WHERE time >= ((CAST(strftime('%s', 'now') AS INTEGER) * 1000) - 60000);"
    if sqlite3_prepare_v2(db, queryString, -1, &queryStatement, nil) == SQLITE_OK {
        while sqlite3_step(queryStatement) == SQLITE_ROW {
            let queryResultCol1 = sqlite3_column_int(queryStatement, 0)
            if queryResultCol1 > 0 {
                running = true
            }
        }
    } else {
        let errorMessage = String(cString: sqlite3_errmsg(db))
        print("Query could not be prepared! \(errorMessage)")
    }

    sqlite3_finalize(queryStatement)
    sqlite3_close(db)

    return running
}

public func getNameByAppName(appName: String) -> String {
    let runningApps = NSWorkspace.shared.runningApplications
    for app in runningApps {
        if app.bundleIdentifier == appName {
            return app.localizedName ?? "No Data"
        }
    }

    let components = appName.split(separator: ".")
    if let lastComponent = components.last {
        return String(lastComponent)
    }

    return "No Data"
}

public func getIconByAppName(appName: String) -> NSImage? {
    let runningApps = NSWorkspace.shared.runningApplications
    for app in runningApps {
        if app.bundleIdentifier == appName {
            return app.icon
        }
    }
    return NSImage(systemSymbolName: "terminal", accessibilityDescription: nil)
}

func getMachineId() -> String{
    var db: OpaquePointer?
    var machineId = ""

    if sqlite3_open(db_path, &db) != SQLITE_OK { // Open database
        print("error opening database")
        return ""
    }

    var queryStatement: OpaquePointer?
    let queryString = "SELECT machine_uuid FROM settings LIMIT 1"

    if sqlite3_prepare_v2(db, queryString, -1, &queryStatement, nil) == SQLITE_OK {
        while sqlite3_step(queryStatement) == SQLITE_ROW {
            let queryResultCol1 = sqlite3_column_text(queryStatement, 0)
            machineId = String(cString: queryResultCol1!)
            print("Machine ID: \(machineId)")
        }
    } else {
        let errorMessage = String(cString: sqlite3_errmsg(db))
        print("Query could not be prepared! \(errorMessage)")
    }

    sqlite3_finalize(queryStatement)
    sqlite3_close(db)

    return machineId
}

func checkDB() -> Bool {
    let fileManager = FileManager.default
    return fileManager.fileExists(atPath: db_path)
}


class LoadingClass {
    
    var lookBackTime:Int = 0

    
    @Published var isLoading: Bool = false
    
    func loadDataFrom() {
        fatalError("loadDataFrom() must be overridden in subclasses")
    }

    public func refreshData(lookBackTime: Int = 0) -> Void{
        if self.isLoading == true {
            return
        }

        self.isLoading = true
        self.lookBackTime = lookBackTime

        DispatchQueue.global(qos: .userInitiated).async {
            self.loadDataFrom()
            DispatchQueue.main.async {
                self.isLoading = false
            }

        }
    }
}

class ValueManager: LoadingClass, ObservableObject{
    

    @Published var energy: Int64 = 0
    @Published var providerRunning: Bool = false
    @Published var topApp: String = "Loading..."


    enum ValueType {
        case int
        case string
    }

    override func loadDataFrom() {
        var db: OpaquePointer?


        if sqlite3_open(db_path, &db) != SQLITE_OK { // Open database
            print("error opening database")
            return
        }

        var newEnergy: Int64 = 0
        var energyQuery:String
        if self.lookBackTime == 0 {
            energyQuery = "SELECT COALESCE(sum(combined_energy), 0) FROM power_measurements;"
        }else{
            energyQuery = "SELECT COALESCE(sum(combined_energy), 0) FROM power_measurements WHERE time >= ((CAST(strftime('%s', 'now') AS INTEGER) * 1000) - \(self.lookBackTime));"
        }
        if let result: Int64 = queryDatabase(db: db, query:energyQuery, type: .int) {
            newEnergy = result
        }


        var newTopApp: String = "Loading"
        var topQuery:String

        if self.lookBackTime == 0 {
            topQuery = """
                SELECT name
                FROM top_processes
                GROUP BY name
                ORDER BY SUM(energy_impact) DESC
                LIMIT 1; -- to get only the top name
                """
        }else{
            topQuery = """
                SELECT name
                FROM top_processes
                WHERE time >= ((CAST(strftime('%s', 'now') AS INTEGER) * 1000) - \(self.lookBackTime))
                GROUP BY name
                ORDER BY SUM(energy_impact) DESC
                LIMIT 1; -- to get only the top name
                """
        }

        if let result: String = queryDatabase(db: db, query:topQuery, type: .string) {
            newTopApp = String(result)
        } else {
            newTopApp = "No data"
        }

        let newScriptRunning = isScriptRunning(scriptName: "power_logger.py")

        DispatchQueue.main.async {
            self.energy = newEnergy
            self.providerRunning = newScriptRunning
            self.topApp = newTopApp
        }

        sqlite3_close(db)

    }


    private func queryDatabase<T>(db: OpaquePointer?, query: String, type: ValueType) -> T? {
        var queryStatement: OpaquePointer?

        if sqlite3_prepare_v2(db, query, -1, &queryStatement, nil) == SQLITE_OK {
            if sqlite3_step(queryStatement) == SQLITE_ROW {
                switch type {
                case .int:
                    let value = sqlite3_column_int64(queryStatement, 0)
                    sqlite3_finalize(queryStatement)
                    return value as? T
                case .string:
                    if let cString = sqlite3_column_text(queryStatement, 0) {
                        let value = String(cString: cString)
                        sqlite3_finalize(queryStatement)
                        return value as? T
                    }
                }
            }
        }
        sqlite3_finalize(queryStatement)
        return nil
    }
}

struct TopProcess: Codable, Identifiable {
    let id: UUID = UUID()  // Add this line if you want a unique identifier
    let name: String
    let energy_impact: Int64
    let cputime_per: Int32

    enum CodingKeys: String, CodingKey {
        case name, energy_impact, cputime_per
    }
}

class TopProcessData: LoadingClass, Identifiable, ObservableObject, RandomAccessCollection {
    typealias Element = TopProcess
    typealias Index = Array<TopProcess>.Index

    @Published var lines: [TopProcess] = []

    var startIndex: Index { lines.startIndex }
    var endIndex: Index { lines.endIndex }

    subscript(position: Index) -> Element {
        lines[position]
    }

    func sort(using sortOrder: [KeyPathComparator<TopProcess>]) {
        // Implement sorting logic
        lines.sort { a, b in
            for comparator in sortOrder {
                switch comparator.compare(a, b) {
                case .orderedAscending:
                    return true
                case .orderedDescending:
                    return false
                case .orderedSame:
                    continue
                }
            }
            return false
        }
    }


    override func loadDataFrom() {

         var db: OpaquePointer?

         if sqlite3_open(db_path, &db) != SQLITE_OK {
             print("error opening database")
             return
         }

        var queryStatement: OpaquePointer?

        let queryString: String
        if self.lookBackTime == 0 {
            queryString = """
                SELECT name, SUM(energy_impact), AVG(cputime_per)
                FROM top_processes
                GROUP BY name
                ORDER BY SUM(energy_impact) DESC
                LIMIT 50;

                """
        } else {
            queryString = """
                SELECT name, SUM(energy_impact), AVG(cputime_per)
                FROM top_processes
                WHERE time >= ((CAST(strftime('%s', 'now') AS INTEGER) * 1000) - \(self.lookBackTime))
                GROUP BY name
                ORDER BY SUM(energy_impact) DESC
                LIMIT 50;
            """
        }
        if sqlite3_prepare_v2(db, queryString, -1, &queryStatement, nil) == SQLITE_OK {
            var newLines: [TopProcess] = []
            while sqlite3_step(queryStatement) == SQLITE_ROW {
                var name: String = ""
                if let namePointer = sqlite3_column_text(queryStatement, 0) {
                    name = String(cString: namePointer)
                }
                let energy_impact = sqlite3_column_int64(queryStatement, 1)
                let cputime_per = sqlite3_column_int(queryStatement, 2)

                newLines.append(TopProcess(name: name, energy_impact: energy_impact, cputime_per: cputime_per))
            }
            DispatchQueue.main.async {
                self.lines = newLines
            }
        }

        sqlite3_finalize(queryStatement)
        sqlite3_close(db)
    }
}




struct DataPoint: Codable, Identifiable {
    let id: Int64
    let combined_energy: Int64
    let cpu_energy: Int64
    let gpu_energy: Int64
    let ane_energy: Int64
    var time: Date?

    enum CodingKeys: String, CodingKey {
        case id, combined_energy, cpu_energy, gpu_energy, ane_energy
    }
}

class ChartData: LoadingClass, ObservableObject, RandomAccessCollection {
    typealias Element = DataPoint
    typealias Index = Array<DataPoint>.Index

    @Published var points: [DataPoint] = []

    var startIndex: Index { points.startIndex }
    var endIndex: Index { points.endIndex }

    subscript(position: Index) -> Element {
        points[position]
    }


    override func loadDataFrom() {

         var db: OpaquePointer? // SQLite database object

        if sqlite3_open(db_path, &db) != SQLITE_OK { // Open database
             print("error opening database")
             return
         }

        var queryStatement: OpaquePointer?

        let queryString: String
        if self.lookBackTime == 0 {
            queryString = "SELECT * FROM power_measurements;"
        } else {
            queryString = "SELECT * FROM power_measurements WHERE time >= ((CAST(strftime('%s', 'now') AS INTEGER) * 1000) - \(self.lookBackTime));"
        }
        if sqlite3_prepare_v2(db, queryString, -1, &queryStatement, nil) == SQLITE_OK {
            var newPoints: [DataPoint] = []
            while sqlite3_step(queryStatement) == SQLITE_ROW {
                let id = sqlite3_column_int64(queryStatement, 0)
                let combined_energy = sqlite3_column_int64(queryStatement, 2)
                let cpu_energy = sqlite3_column_int64(queryStatement, 3)
                let gpu_energy = sqlite3_column_int64(queryStatement, 4)
                let ane_energy = sqlite3_column_int64(queryStatement, 5)
                let time = Date(timeIntervalSince1970: Double(id) / 1000.0)

                let dataPoint = DataPoint(id: id, combined_energy: combined_energy, cpu_energy: cpu_energy, gpu_energy: gpu_energy, ane_energy: ane_energy, time: time)

                newPoints.append(dataPoint)
            }
            DispatchQueue.main.async {
                self.points = newPoints
            }
        }

        sqlite3_finalize(queryStatement)
        sqlite3_close(db)
    }
}


struct PointsGraph: View {
    @ObservedObject var chartData: ChartData

    init(chartData: ChartData) {
        self.chartData = chartData
    }

    var body: some View {
        if chartData.isLoading {
            ProgressView("Loading...")
                .scaleEffect(1.5, anchor: .center)
                .progressViewStyle(CircularProgressViewStyle(tint: Color.blue))
                .padding()
        } else {
            VStack {
                Chart(chartData) {
                    BarMark(
                        x: .value("Time", $0.time!),
                        y: .value("Energy", $0.combined_energy)
                    )
                }
                .chartYAxisLabel("mJ")
                .chartXAxisLabel("Time")
            }
        }
    }
}

struct TopProcessTable: View {
    @ObservedObject var tpData: TopProcessData
    @State private var sortOrder = [
        //KeyPathComparator(\TopProcess.name, order: .forward),
        KeyPathComparator(\TopProcess.energy_impact, order: .forward),
        KeyPathComparator(\TopProcess.cputime_per, order: .forward),
    ]
    @Environment(\.colorScheme) var colorScheme

    var tableColour: Color {
        return colorScheme == .dark ? Color.white : Color.primary
    }

    init(tpData: TopProcessData) {
        self.tpData = tpData
    }

    var body: some View {
        if tpData.isLoading {
            ProgressView("Loading...")
                .scaleEffect(1.5, anchor: .center)
                .progressViewStyle(CircularProgressViewStyle(tint: Color.blue))
                .padding()
        } else {
            if tpData.isEmpty {
            } else {
                VStack{
                    Table(tpData, sortOrder: $sortOrder) {
                        TableColumn(""){ line in
                            Image(nsImage: getIconByAppName(appName: line.name) ?? NSImage())
                                .resizable()
                                .frame(width: 15, height: 15)
                                .padding(EdgeInsets(top: 0, leading: 0, bottom: 0, trailing: 0))

                        }.width(20)

                        TableColumn("Name", value: \TopProcess.name)
                        TableColumn("Energy Impact", value: \TopProcess.energy_impact){ line in
                            Text(String(line.energy_impact))
                        }
                        TableColumn("AVG CPU time %", value: \TopProcess.cputime_per){ line in
                            Text(String(line.cputime_per))
                        }
                    }
                    .onChange(of: sortOrder) { newOrder in
                        tpData.sort(using: newOrder)
                    }.foregroundColor(tableColour)


                    .tableStyle(.bordered(alternatesRowBackgrounds: true))
                    HStack {
                        Spacer()  // Pushes the Link to the right side.
                        Link("Description", destination: URL(string: "https://github.com/green-coding-berlin/hog#the-desktop-app")!)
                            .font(.footnote)  // This makes the font size smaller.
                    }
                }.padding()
            }
        }
    }
}

struct TextInputView: View {
    @Binding var text: String
    @Binding var isPresented: Bool

    var body: some View {
        VStack() {
            TextField("Enter text here", text: $text)
            Button("Done") {
                isPresented = false
            }
        }
        .padding()
    }
}


struct DataView: View {
    
    @StateObject var chartData = ChartData()
    @StateObject var lineData = TopProcessData()
    @StateObject var valueManager = ValueManager()
    @StateObject var settingsManager = SettingsManager()
    
    @State private var isHovering = false
    @State private var refreshFlag = false

    var lookBackTime: Int
    var viewModel: ViewModel
    var whoAmI: TabSelection


    @State private var text: String = ""
    @State private var isTextInputViewPresented: Bool = false

    func refresh() {
        self.chartData.refreshData(lookBackTime: self.lookBackTime)
        self.lineData.refreshData(lookBackTime: self.lookBackTime)
        self.valueManager.refreshData(lookBackTime: self.lookBackTime)
    }

    init(lookBackTime: Int = 0, viewModel: ViewModel, whoAmI: TabSelection) {
        self.lookBackTime = lookBackTime
        self.viewModel = viewModel
        self.whoAmI = whoAmI
    }

    var body: some View {
        VStack(){
            if chartData.isLoading == false && chartData.isEmpty {
                Text("No Data for this timeframe!").font(.largeTitle)
                Text("Please make sure the data collection app is running! For more details please check out the documentation under:")
                Link(destination: URL(string: "https://github.com/green-coding-berlin/hog#power-logger")!) {
                    Text("https://github.com/green-coding-berlin/hog#power-logger")
                }
            }else{
                HStack {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("This is a very minimalistic overview of your energy usage.")
                    }
                    
                    Spacer(minLength: 10)
                    
                    Button(action: {
                        self.refresh()
                    }) {
                        Image(systemName: "goforward")
                    }
                    Button(action: {
                        exit(0)
                    }) {
                        Image(systemName: "x.circle")
                    }
                    
                }
                VStack{
                    
                    VStack(spacing: 0) {
                        if valueManager.isLoading {
                            Text("Loading")
                        } else {
                            ProcessBadge(title: "App with the highest energy usage", color: Color("chartColor2"), process: valueManager.topApp)
                            EnergyBadge(title: "System energy usage", color: Color("chartColor2"), image: "clock.badge.checkmark", value: valueManager.energy)
                            if valueManager.providerRunning {
                                TextBadge(title: "", color: Color("chartColor2"), image: "checkmark.seal", value: "All measurement systems are functional")
                            } else {
                                HStack{
                                    TextBadge(title: "", color: Color("redish"), image: "exclamationmark.octagon", value: "Measurement systems not running!")
                                    Link(destination: URL(string: "https://github.com/green-coding-berlin/hog#power-logger")!) {
                                        Image(systemName: "questionmark.circle.fill")
                                            .font(.system(size: 24))
                                    }
                                }
                            }
                            //                        HStack{
                            //                            TextBadge(title: "", color: Color("menuTab"), image: "person.crop.circle.badge.clock", value: "Project: Hog Development")
                            //                            Button(action: {
                            //                                isTextInputViewPresented = true
                            //                            }) {
                            //                                Image(systemName: "pencil.circle")
                            //                            }
                            //
                            //                        }
                            //                        .sheet(isPresented: $isTextInputViewPresented) {
                            //                            TextInputView(text: $text, isPresented: $isTextInputViewPresented)
                            //                        }
                        }
                        Button(action: {
                            if let url = URL(string: "\(settingsManager.web_url)\(settingsManager.machine_uuid)") {
                                NSWorkspace.shared.open(url)
                            }
                        }) {
                            Text("View Detailed Analytics")
                                .padding(10)
                        }
                        
                        
                    }
                    
                    PointsGraph(chartData: chartData)
                    TopProcessTable(tpData: lineData)
                    
                }
            }

        }
        .padding()
        .onReceive(viewModel.$selectedTab) { tab in
            if tab == self.whoAmI {
                self.refresh()
            }
        }

    }
}


@ViewBuilder
func ProcessBadge(title: String, color: Color, process: String)->some View {
    HStack {
        Image(nsImage: getIconByAppName(appName: process) ?? NSImage())
            .font(.title2)
            .foregroundColor(color)
            .padding(10)

        Text(getNameByAppName(appName: process))
            .font(.title2.bold())

        Text(title)
            .font(.caption2.bold())

    }
    .frame(maxWidth: .infinity, alignment: .leading)
}

func formatEnergy(_ mJ: Int64) -> String {
    let joules = Double(mJ) / 1000.0
    let wattHours = joules / 3600.0
    let wattMinutes = joules / 60.0

    if wattHours >= 1 {
        return String(format: "%.2f Watt Hours", wattHours)
    } else {
        return String(format: "%.2f Watt Min", wattMinutes)
    }
}



@ViewBuilder
func EnergyBadge(title: String, color: Color, image: String, value: Int64)->some View {
    HStack {
        Image(systemName: image)
            .font(.title2)
            .foregroundColor(color)
            .padding(10)

            Text(String(format: "%@", formatEnergy(value)))
                .font(.title2.bold())

            Text(title)
                .font(.caption2.bold())
    }
    .frame(maxWidth: .infinity, alignment: .leading)
}

@ViewBuilder
func TextBadge(title: String, color: Color, image: String, value: String)->some View {
    HStack {
        Image(systemName: image)
            .font(.title2)
            .foregroundColor(color)
            .padding(10)

            Text(value)
                .font(.title2.bold())

            Text(title)
                .font(.caption2.bold())
    }
    .frame(maxWidth: .infinity, alignment: .leading)
}


class WindowFocusTracker: ObservableObject {
    @Published var isKeyWindow: Bool = false
    private var cancellables: Set<AnyCancellable> = []

    init() {
        NSApplication.shared.publisher(for: \.keyWindow)
            .sink { [weak self] keyWindow in
                self?.isKeyWindow = (keyWindow != nil)
            }
            .store(in: &cancellables)
    }
}

enum TabSelection: Hashable {
    case last5Minutes, last24Hours, allTime, settings
}


class ViewModel: ObservableObject {
    @Published var renderToggle: Bool = false
    @Published var selectedTab: TabSelection = .last5Minutes

    func toggleRender() {
        renderToggle.toggle()
    }
}

struct DetailView: View {
    
    @ObservedObject var windowFocusTracker = WindowFocusTracker()
    @ObservedObject var viewModel = ViewModel()
    @Environment(\.colorScheme) var colorScheme

    var body: some View {
        if checkDB(){
            if windowFocusTracker.isKeyWindow{
                ReleaseCheckerView()
                TabView(selection: $viewModel.selectedTab) {
                    DataView(lookBackTime: 300000, viewModel: viewModel, whoAmI: TabSelection.last5Minutes)
                        .tabItem {
                            Label("Last 5 Minutes", systemImage: "list.dash")
                        }
                        .tag(TabSelection.last5Minutes)
                    
                    
                    DataView(lookBackTime: 86400000, viewModel: viewModel, whoAmI: TabSelection.last24Hours)
                        .tabItem {
                            Label("Last 24 Hours", systemImage: "square.and.pencil")
                        }
                        .tag(TabSelection.last24Hours)
                    
                    
                    DataView(viewModel: viewModel, whoAmI: TabSelection.allTime)
                        .tabItem {
                            Label("All Time", systemImage: "square.and.pencil")
                        }
                        .tag(TabSelection.allTime)
                    
                    
                    SettingsView(viewModel: viewModel, whoAmI: TabSelection.settings)
                        .tabItem {
                            Label("Settings", systemImage: "square.and.pencil")
                        }
                        .tag(TabSelection.settings)
                    
                }
                .padding()
                .background(colorScheme == .light ? Color.white : Color.black)
            }else{
                Text("Please return focus to window to display data. You can do this by clicking here.")
            }
        } else {
            InstallView(viewModel: viewModel)
        }
    }
}

struct DetailView_Previews: PreviewProvider {
    static var previews: some View {
        DetailView().fixedSize()

    }
}
