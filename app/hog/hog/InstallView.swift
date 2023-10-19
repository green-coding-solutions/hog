//
//  InstallView.swift
//  hog
//
//  Created by Didi Hoffmann on 18.10.23.
//

import SwiftUI

struct OneView: View {

    var body: some View {
        Text("1) Open Terminal").font(.headline)
        HStack{
            Button(action: {
                let workspace = NSWorkspace.shared
                if let url = URL(string: "file:///System/Applications/Utilities/Terminal.app") {
                    let configuration = NSWorkspace.OpenConfiguration()
                    workspace.open(url, configuration: configuration, completionHandler: nil)
                }
            }) {
                HStack {
                    Image(systemName: "terminal") // This is a symbolic representation, actual symbol might differ.
                    Text("Terminal")
                }
            }

            Text("If the button does not work please look under the Utilities folder in your Apps and start the terminal.")
        }.padding()
    }
}

struct CopyPasteTextField: NSViewRepresentable {
    @Binding var text: String

    func makeNSView(context: Context) -> NSTextField {
        let textField = NSTextField()
        textField.isBordered = true
        textField.backgroundColor = NSColor.textBackgroundColor
        return textField
    }

    func updateNSView(_ nsView: NSTextField, context: Context) {
        nsView.stringValue = text
    }
}


struct TwoView: View {
    @State private var text = "sudo bash -c \"$(curl -fsSL https://raw.githubusercontent.com/green-coding-berlin/hog/main/install.sh)\""

    var body: some View {
        Text("2) Run this command").font(.headline)

        HStack(spacing: 20) {
            CopyPasteTextField(text: $text)

            Button("Copy Text") {
                let pasteboard = NSPasteboard.general
                pasteboard.clearContents()
                pasteboard.setString(text, forType: .string)
            }
        }.padding()
    }
}
struct ThreeView: View {
    @State private var showInfo: Bool = false

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text("3) You will need to enter your password and install xcode tools.").font(.headline)
                Button(action: {
                    showInfo.toggle()
                }) {
                    Image(systemName: "info.circle")
                }
            }
            if showInfo {
                Text("We are very aware that this is a risky operation. The problem is that the program needs to run as root and also the installer needs to activate the program.")
            }
        }
    }
}


struct StepsView: View {
    var body: some View {
        HStack{
            Image("logo2")
                .resizable()
                .scaledToFit()
                .frame(width: 50, height: 50)
            Text("Welcome to the hog").font(.title)
            Spacer()
            Button(action: {
                exit(0)
            }) {
                Image(systemName: "x.circle")
            }

        }
        Text("It looks like you haven't installed the program that we need to collect the power measurments. Please follow these steps:")
        Divider()
        OneView()
        TwoView()
        ThreeView()
        Text("4) All done. Now check").font(.headline)

    }
}


struct InstallView: View {
    @ObservedObject var viewModel: ViewModel

    @State private var showingAlert = false

    var body: some View {
        VStack(alignment: .leading, spacing: 10) { // Set alignment to .leading

            StepsView()
            Button("Re-check if the power data is reported") {
                viewModel.toggleRender()

            }.padding()
            Divider()
            Text("If you just want to see the interface you can also load some demo data visualises what is possible with the hog.")
            Button("View with demo data") {
                guard let sourceURL = Bundle.main.url(forResource: "demo_db", withExtension: "db") else {
                    print("Source file not found!")
                    return
                }
                db_path = sourceURL.path()
                viewModel.selectedTab = .allTime
                viewModel.toggleRender()
            }
            .alert(isPresented: $showingAlert) {
                Alert(title: Text("There was an error copying demo data."),
                      message: Text("Please look at the logs and submit an issue! https://github.com/green-coding-berlin/hog/issues/new"),
                      dismissButton: .default(Text("Got it!")))
            }
            Divider()
            Text("You can also read our documentation for all the details under: https://github.com/green-coding-berlin/hog")

        }.padding()

    }

}
