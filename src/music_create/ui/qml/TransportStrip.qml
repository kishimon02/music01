import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import QtQml 2.15

Rectangle {
    id: root
    color: "#171B22"
    radius: 10
    border.color: "#2D3641"
    border.width: 1
    implicitHeight: 78

    property var transportState

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 12
        spacing: 8

        RowLayout {
            Layout.fillWidth: true
            spacing: 10

            Label {
                Layout.fillWidth: true
                text: root.transportState ? root.transportState.playheadText : "001.01.000"
                color: "#F2F6FB"
                font.pixelSize: 28
                font.bold: true
            }

            Label {
                text: root.transportState ? root.transportState.tempoText : "120 BPM / 4/4"
                color: "#A0AFBF"
                font.pixelSize: 12
                font.bold: true
            }

            Rectangle {
                color: "#232A34"
                radius: 999
                border.color: "#374252"
                border.width: 1
                implicitHeight: 30
                implicitWidth: 110

                Label {
                    anchors.centerIn: parent
                    text: root.transportState ? root.transportState.rangeText : "64 bars"
                    color: "#D7E0EC"
                    font.pixelSize: 11
                    font.bold: true
                }
            }
        }

        Slider {
            id: playheadSlider
            Layout.fillWidth: true
            from: 100
            to: root.transportState ? root.transportState.playheadMaximum : 6400

            onMoved: {
                if (root.transportState) {
                    root.transportState.requestPlayheadFromSlider(Math.round(value))
                }
            }

            onPressedChanged: {
                if (!pressed && root.transportState) {
                    root.transportState.requestPlayheadFromSlider(Math.round(value))
                }
            }
        }

        Binding {
            target: playheadSlider
            property: "value"
            value: root.transportState ? root.transportState.playheadValue : 100
            when: !playheadSlider.pressed
        }
    }
}
