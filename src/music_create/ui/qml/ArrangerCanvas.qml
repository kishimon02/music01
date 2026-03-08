import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

Rectangle {
    id: root
    color: "#171B22"
    radius: 10
    border.color: "#2D3641"
    border.width: 1
    clip: true

    property var sceneModel
    property int laneHeight: 56
    property int rulerHeight: 38
    property int labelWidth: 220
    property int zoomLevel: sceneModel ? sceneModel.zoomLevel : 16
    property int totalBars: sceneModel ? sceneModel.totalBars : 64
    property real timelineWidth: totalBars * zoomLevel
    property var tracks: sceneModel ? sceneModel.tracks : []
    property bool dragActive: false
    property int dragLaneIndex: -1
    property int draftStartBar: 1
    property int draftEndBar: 1

    function labelStep() {
        if (zoomLevel >= 32) {
            return 1
        }
        if (zoomLevel >= 16) {
            return 4
        }
        if (zoomLevel >= 8) {
            return 8
        }
        return 16
    }

    function barFromLaneX(xValue) {
        var computed = Math.floor(xValue / zoomLevel) + 1
        return Math.max(1, Math.min(totalBars, computed))
    }

    function draftRectX() {
        return (Math.min(draftStartBar, draftEndBar) - 1) * zoomLevel + 2
    }

    function draftRectWidth() {
        return Math.max((Math.abs(draftEndBar - draftStartBar) + 1) * zoomLevel - 4, 8)
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 10
        spacing: 10

        Rectangle {
            id: minimapFrame
            Layout.fillWidth: true
            Layout.preferredHeight: 68
            radius: 8
            color: "#14181D"
            border.color: "#29313C"
            border.width: 1

            Canvas {
                id: minimapCanvas
                anchors.fill: parent
                anchors.margins: 6

                onPaint: {
                    var ctx = getContext("2d")
                    ctx.clearRect(0, 0, width, height)
                    ctx.fillStyle = "#101419"
                    ctx.fillRect(0, 0, width, height)

                    var trackCount = root.tracks.length
                    if (trackCount <= 0 || root.totalBars <= 0) {
                        return
                    }

                    var rowHeight = height / trackCount
                    for (var trackIndex = 0; trackIndex < trackCount; ++trackIndex) {
                        var track = root.tracks[trackIndex]
                        ctx.fillStyle = trackIndex % 2 === 0 ? "#151B22" : "#12171D"
                        ctx.fillRect(0, trackIndex * rowHeight, width, rowHeight - 1)

                        for (var clipIndex = 0; clipIndex < track.clips.length; ++clipIndex) {
                            var clip = track.clips[clipIndex]
                            var clipX = ((clip.startBar - 1) / root.totalBars) * width
                            var clipW = Math.max((clip.lengthBars / root.totalBars) * width, 2)
                            ctx.fillStyle = clip.color || (clip.clipType === "midi" ? "#4D8FF4" : "#D97A36")
                            ctx.fillRect(clipX, trackIndex * rowHeight + 6, clipW, Math.max(rowHeight - 12, 4))
                        }
                    }

                    var maxScroll = Math.max(timelineFlick.contentWidth - timelineFlick.width, 1)
                    var viewportX = (timelineFlick.contentX / maxScroll) * width
                    var viewportW = (timelineFlick.width / timelineFlick.contentWidth) * width
                    ctx.strokeStyle = "#FF8A4C"
                    ctx.lineWidth = 2
                    ctx.strokeRect(viewportX, 2, Math.max(viewportW, 14), height - 4)
                }
            }

            MouseArea {
                anchors.fill: parent

                onClicked: function(mouse) {
                    var ratio = mouse.x / width
                    var maxScroll = Math.max(timelineFlick.contentWidth - timelineFlick.width, 0)
                    timelineFlick.contentX = ratio * maxScroll
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            color: "#11161D"
            radius: 8
            border.color: "#2A313B"
            border.width: 1

            Flickable {
                id: timelineFlick
                anchors.fill: parent
                anchors.margins: 1
                contentWidth: root.labelWidth + root.timelineWidth
                contentHeight: root.rulerHeight + ((root.tracks.length + 1) * root.laneHeight)
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                flickableDirection: Flickable.HorizontalAndVerticalFlick

                onContentXChanged: minimapCanvas.requestPaint()
                onWidthChanged: minimapCanvas.requestPaint()

                Item {
                    id: timelineContent
                    width: timelineFlick.contentWidth
                    height: timelineFlick.contentHeight

                    Canvas {
                        id: gridCanvas
                        anchors.fill: parent

                        onPaint: {
                            var ctx = getContext("2d")
                            ctx.clearRect(0, 0, width, height)
                            ctx.fillStyle = "#151A21"
                            ctx.fillRect(0, 0, width, height)

                            ctx.fillStyle = "#171D25"
                            ctx.fillRect(0, 0, root.labelWidth, height)

                            for (var row = 0; row < root.tracks.length + 1; ++row) {
                                var top = root.rulerHeight + row * root.laneHeight
                                ctx.fillStyle = row % 2 === 0 ? "#171C23" : "#151920"
                                ctx.fillRect(root.labelWidth, top, root.timelineWidth, root.laneHeight)
                            }

                            for (var bar = 0; bar <= root.totalBars; ++bar) {
                                var x = root.labelWidth + bar * root.zoomLevel
                                ctx.strokeStyle = (bar % 4 === 0) ? "#313C49" : "#252E39"
                                ctx.lineWidth = 1
                                ctx.beginPath()
                                ctx.moveTo(x + 0.5, 0)
                                ctx.lineTo(x + 0.5, height)
                                ctx.stroke()
                            }

                            for (var lane = 0; lane <= root.tracks.length + 1; ++lane) {
                                var laneY = root.rulerHeight + lane * root.laneHeight
                                ctx.strokeStyle = "#242D38"
                                ctx.lineWidth = 1
                                ctx.beginPath()
                                ctx.moveTo(0, laneY + 0.5)
                                ctx.lineTo(width, laneY + 0.5)
                                ctx.stroke()
                            }

                            if (root.sceneModel) {
                                var selectedX = root.labelWidth + (root.sceneModel.selectedBar - 1) * root.zoomLevel
                                ctx.fillStyle = "rgba(255, 138, 76, 0.07)"
                                ctx.fillRect(selectedX, 0, root.zoomLevel, height)

                                var playheadX = root.labelWidth + (root.sceneModel.playheadBar - 1) * root.zoomLevel
                                ctx.strokeStyle = "#FF8A4C"
                                ctx.lineWidth = 2
                                ctx.beginPath()
                                ctx.moveTo(playheadX + 0.5, 0)
                                ctx.lineTo(playheadX + 0.5, height)
                                ctx.stroke()
                            }
                        }
                    }

                    Rectangle {
                        x: 0
                        y: 0
                        width: root.labelWidth
                        height: root.rulerHeight
                        color: "#171D25"
                    }

                    Rectangle {
                        x: root.labelWidth
                        y: 0
                        width: root.timelineWidth
                        height: root.rulerHeight
                        color: "#171D25"
                    }

                    Repeater {
                        model: Math.ceil(root.totalBars / root.labelStep())

                        delegate: Item {
                            property int barNumber: index * root.labelStep() + 1

                            visible: barNumber <= root.totalBars
                            x: root.labelWidth + (barNumber - 1) * root.zoomLevel
                            y: 0
                            width: root.zoomLevel * root.labelStep()
                            height: root.rulerHeight

                            Label {
                                anchors.left: parent.left
                                anchors.leftMargin: 6
                                anchors.verticalCenter: parent.verticalCenter
                                text: root.sceneModel ? root.sceneModel.rulerLabel(barNumber) : String(barNumber)
                                color: "#9AA6B5"
                                font.pixelSize: 11
                                font.bold: barNumber % 4 === 1
                            }
                        }
                    }

                    Repeater {
                        model: root.tracks.length + 1

                        delegate: Item {
                            property bool emptyLane: index >= root.tracks.length
                            property var trackData: emptyLane ? null : root.tracks[index]

                            x: 0
                            y: root.rulerHeight + index * root.laneHeight
                            width: timelineContent.width
                            height: root.laneHeight

                            Rectangle {
                                width: root.labelWidth
                                height: parent.height
                                color: emptyLane
                                    ? "#151A21"
                                    : (trackData.trackId === (root.sceneModel ? root.sceneModel.selectedTrackId : "") ? "#212B37" : "#171D25")
                            }

                            Column {
                                anchors.left: parent.left
                                anchors.leftMargin: 14
                                anchors.verticalCenter: parent.verticalCenter
                                spacing: 2

                                Label {
                                    text: emptyLane ? "新規トラック" : trackData.name
                                    color: emptyLane ? "#B9C4D3" : "#F0F4FA"
                                    font.pixelSize: 13
                                    font.bold: true
                                }

                                Label {
                                    text: emptyLane ? "鉛筆で描画して追加" : (trackData.instrumentName + " / " + trackData.trackId)
                                    color: "#7E8C9C"
                                    font.pixelSize: 11
                                }
                            }

                            Item {
                                x: root.labelWidth
                                width: root.timelineWidth
                                height: parent.height

                                Rectangle {
                                    visible: root.dragActive && root.dragLaneIndex === index
                                    x: root.draftRectX()
                                    y: 8
                                    width: root.draftRectWidth()
                                    height: parent.height - 16
                                    radius: 7
                                    color: Qt.rgba(77 / 255, 143 / 255, 244 / 255, 0.32)
                                    border.color: "#A8CAFF"
                                    border.width: 1
                                }

                                MouseArea {
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: root.sceneModel && root.sceneModel.toolMode === "pencil" ? Qt.CrossCursor : Qt.PointingHandCursor

                                    onPressed: function(mouse) {
                                        if (!root.sceneModel || root.sceneModel.toolMode !== "pencil") {
                                            return
                                        }
                                        root.dragActive = true
                                        root.dragLaneIndex = index
                                        root.draftStartBar = root.barFromLaneX(mouse.x)
                                        root.draftEndBar = root.draftStartBar
                                    }

                                    onPositionChanged: function(mouse) {
                                        if (!root.dragActive || root.dragLaneIndex !== index) {
                                            return
                                        }
                                        root.draftEndBar = root.barFromLaneX(mouse.x)
                                    }

                                    onReleased: function(mouse) {
                                        if (!root.sceneModel) {
                                            root.dragActive = false
                                            root.dragLaneIndex = -1
                                            return
                                        }
                                        if (root.sceneModel.toolMode === "pencil" && root.dragActive && root.dragLaneIndex === index) {
                                            root.draftEndBar = root.barFromLaneX(mouse.x)
                                            root.sceneModel.requestClipCreation(
                                                emptyLane ? "" : trackData.trackId,
                                                Math.min(root.draftStartBar, root.draftEndBar),
                                                Math.max(root.draftStartBar, root.draftEndBar),
                                                index
                                            )
                                        }
                                        root.dragActive = false
                                        root.dragLaneIndex = -1
                                    }

                                    onCanceled: {
                                        root.dragActive = false
                                        root.dragLaneIndex = -1
                                    }

                                    onClicked: function(mouse) {
                                        if (!root.sceneModel || root.sceneModel.toolMode !== "select" || emptyLane) {
                                            return
                                        }
                                        root.sceneModel.requestSelection(trackData.trackId, root.barFromLaneX(mouse.x), "")
                                    }
                                }

                                Repeater {
                                    model: emptyLane ? [] : trackData.clips

                                    delegate: Rectangle {
                                        x: (modelData.startBar - 1) * root.zoomLevel + 2
                                        y: 8
                                        width: Math.max(modelData.lengthBars * root.zoomLevel - 4, 8)
                                        height: parent.height - 16
                                        radius: 7
                                        color: modelData.color || (modelData.clipType === "midi" ? "#4D8FF4" : "#D97A36")
                                        border.color: modelData.clipId === (root.sceneModel ? root.sceneModel.selectedClipId : "") ? "#F5F8FC" : "#34404D"
                                        border.width: modelData.clipId === (root.sceneModel ? root.sceneModel.selectedClipId : "") ? 2 : 1
                                        opacity: trackData.trackId === (root.sceneModel ? root.sceneModel.selectedTrackId : "") ? 0.98 : 0.88

                                        Label {
                                            anchors.fill: parent
                                            anchors.leftMargin: 10
                                            anchors.rightMargin: 10
                                            verticalAlignment: Text.AlignVCenter
                                            elide: Text.ElideRight
                                            text: modelData.name
                                            color: "#F2F6FB"
                                            font.pixelSize: 11
                                            font.bold: true
                                        }

                                        ToolTip.visible: clipMouseArea.containsMouse
                                        ToolTip.text: modelData.tooltip

                                        MouseArea {
                                            id: clipMouseArea
                                            anchors.fill: parent
                                            enabled: root.sceneModel && root.sceneModel.toolMode === "select"
                                            hoverEnabled: true

                                            onClicked: function(mouse) {
                                                var bar = modelData.startBar + Math.floor(mouse.x / root.zoomLevel)
                                                if (root.sceneModel) {
                                                    root.sceneModel.requestSelection(modelData.trackId, bar, modelData.clipId)
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    Connections {
        target: root.sceneModel || null

        function onSceneChanged() {
            gridCanvas.requestPaint()
            minimapCanvas.requestPaint()
        }
    }
}
