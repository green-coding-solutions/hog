import SwiftUI
import Foundation
import Charts

// MARK: - Models

struct EmissionsDetail: Decodable {
    let Percentage: Double
    let Emissions: Double
}

struct EmissionsBreakdown: Decodable {
    let Production: EmissionsDetail
    let Transportation: EmissionsDetail
    let ProductUse: EmissionsDetail?
    let EndOfLifeProcessing: EmissionsDetail?
    
    // A computed property to unify keys
    var breakdownEntries: [(String, EmissionsDetail)] {
        var result: [(String, EmissionsDetail)] = []
        if let production = Production as EmissionsDetail? {
            result.append(("Production", production))
        }
        if let transportation = Transportation as EmissionsDetail? {
            result.append(("Transportation", transportation))
        }
        // Attempt to use the "Product Use" key
        if let productUse = ProductUse {
            result.append(("Product Use", productUse))
        } else if let productUse = ProductUse {
            result.append(("Product Use", productUse))
        }
        // Attempt end of life key
        if let eol = EndOfLifeProcessing {
            result.append(("End-of-life Processing", eol))
        } else if let eol = EndOfLifeProcessing {
            result.append(("End-of-life Processing", eol))
        }
        
        return result
    }
}

struct DeviceCarbonData: Decodable {
    let Device: String
    let TotalEmissions: Double?
    let EmissionsBreakdown: EmissionsBreakdown
    let models: [String]?
    let date: String?
    
    var totalEmissionsFormatted: String {
        if let total = TotalEmissions {
            return "\(total) kg CO₂e"
        }
        return "Data not available"
    }
    
    var chartData: [(category: String, val: Double)] {
        return EmissionsBreakdown.breakdownEntries.map { ($0.0, $0.1.Emissions) }
    }
}


struct EmbodiedCarbonView: View {
    @State private var modelIdentifier: String = ""
    @State private var selectedDeviceKey: String = ""
    @State private var devices: [String: DeviceCarbonData] = [:]

    @ObservedObject var settingsManager = SettingsManager()
    var viewModel: ViewModel
    var whoAmI: TabSelection

    init(viewModel: ViewModel, whoAmI: TabSelection){
        self.viewModel = viewModel
        self.whoAmI = whoAmI
    }

    var body: some View {
        VStack {
            if devices.isEmpty {
                Text("Loading data...")
            } else {
                
                Text("Your device has been selected. Please change if you want to see another device.")
                Picker("Select a Device", selection: $selectedDeviceKey) {
                    ForEach(devices.keys.sorted(by: { devices[$0]!.Device < devices[$1]!.Device }), id: \.self) { key in
                        Text(devices[key]?.Device ?? key).tag(key)
                    }
                }
                .padding()
                
                // Display info about selected device
                if let selectedData = devices[selectedDeviceKey] {
                    
                    Text("Total Embodied Carbon: \(selectedData.totalEmissionsFormatted)")
                        .font(.title)
                        .padding()
                    
                    Text("Emissions by phase in kg CO₂e")
                        .font(.title2)
                        .padding()

                    Chart(selectedData.chartData, id: \.category) { category, val in
                        SectorMark(
                            angle: .value("Value", val),
                            innerRadius: .ratio(0.618),
                            outerRadius: .inset(10),
                            angularInset: 1
                        )
                        .cornerRadius(4)
                        .foregroundStyle(by: .value("Category", category))
                        .annotation(position: .overlay) {
                            Text(String(format: "%.1f", val))
                                //.font()
                                .foregroundStyle(.white)
                        }

                    }
                    .frame(height: 300)
                    .chartLegend(alignment: .center, spacing: 16)


                    
//                    print("Selected chart data: \(selectedData.chartData)")
//
//                    
//                    Chart {
//                        ForEach(selectedData.chartData, id: \.category) { item in
//                            SectorMark(angle: .value("Emissions", item.value))
//                                .foregroundStyle(by: .value("Category", item.category))
//                                .annotation(position: .overlay) {
//                                    Text(item.category)
//                                        .font(.caption)
//                                        .foregroundColor(.white) // Adjust color for visibility
//                                }
//                        }
//                    }
//                    .chartForegroundStyleScale([
//                        "Production": Color.blue,
//                        "Transportation": Color.green,
//                        "ProductUse": Color.orange,
//                        "EndOfLifeProcessing": Color.red
//                    ])
//                    .chartLegend(.visible)
//                    .frame(height: 300)
//                    .padding()
//                    
                    
                } else {
                    Text("No data available for selected device.")
                }
            }
        }
        .onAppear {
            loadData()
        }
    }

    func getMacModelIdentifier() -> String? {
        var size = 0
        sysctlbyname("hw.model", nil, &size, nil, 0)
        var model = [CChar](repeating: 0, count: size)
        if sysctlbyname("hw.model", &model, &size, nil, 0) == 0 {
            return String(cString: model)
        }
        return nil
    }

    func loadData() {

        guard let url = Bundle.main.url(forResource: "mac_embodied_carbon", withExtension: "json"),
              let data = try? Data(contentsOf: url) else {
            print("No data found")
            return
        }
        
        do {
            let json = try JSONSerialization.jsonObject(with: data, options: []) as? [String: Any] ?? [:]
            let decoder = JSONDecoder()
            
            var tempDevices: [String: DeviceCarbonData] = [:]
            for (key, value) in json {
                if let deviceData = try? JSONSerialization.data(withJSONObject: value),
                   let decoded = try? decoder.decode(DeviceCarbonData.self, from: deviceData) {
                    tempDevices[key] = decoded
                }
            }
            
            self.devices = tempDevices
            
            // Try to select the user's device by default
            if let userModel = getMacModelIdentifier() {
                self.modelIdentifier = userModel
                if devices.keys.contains(userModel) {
                    self.selectedDeviceKey = userModel
                } else {
                    // If user device is not in the JSON, just pick the first device
                    self.selectedDeviceKey = devices.keys.first ?? ""
                }
            } else {
                // If we can't get the user model, just pick the first device
                self.selectedDeviceKey = devices.keys.first ?? ""
            }
            
        } catch {
            print("Error parsing JSON: \(error)")
        }
    }
}
