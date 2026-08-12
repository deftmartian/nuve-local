// Generic Qt 6 schedule-time probe for an isolated exact target userland.
//
// This source contains no firmware data. Compile it for the target architecture,
// then execute it with the verified target libraries and timezone database in a
// networkless sandbox. See the firmware-analysis workflow for the full boundary.

#include <QCoreApplication>
#include <QDateTime>
#include <QJSEngine>
#include <QJSValue>
#include <QJsonDocument>
#include <QJsonObject>
#include <QJsonParseError>
#include <QLocale>
#include <QTextStream>
#include <QTime>
#include <QTimeZone>

#include <ctime>

static void printJs(QTextStream &out, QJSEngine &engine, const QString &label,
                    const QString &expression)
{
    const QJSValue value = engine.evaluate(expression);
    out << label << '=';
    if (value.isError())
        out << "ERROR:" << value.property("name").toString();
    else
        out << value.toString();
    out << '\n';
}

int main(int argc, char **argv)
{
    QCoreApplication app(argc, argv);
    QTextStream out(stdout);
    const QLocale locale = QLocale::system();
    out << "qt=" << qVersion() << '\n';
    out << "locale=" << locale.name() << '\n';
    for (const QString &text : {QStringLiteral("12:00 AM"), QStringLiteral("06:00 AM"),
                                QStringLiteral("12:00 PM"), QStringLiteral("11:59 PM"),
                                QStringLiteral("not-a-time")}) {
        const QTime parsed = locale.toTime(text, QStringLiteral("hh:mm AP"));
        out << "parse=" << text << ',' << parsed.isValid() << ','
            << parsed.toString(QStringLiteral("HH:mm:ss.zzz")) << '\n';
    }

    QJSEngine engine;
    printJs(out, engine, QStringLiteral("date_locale_parser_type"),
            QStringLiteral("typeof Date.fromLocaleTimeString"));
    printJs(out, engine, QStringLiteral("spring_set_0230"),
            QStringLiteral("var d=new Date(2026,2,8,0,0,0,0);"
                           "d.setHours(2);d.setMinutes(30);d.setSeconds(0);"
                           "d.setMilliseconds(0);"
                           "[d.getFullYear(),d.getMonth()+1,d.getDate(),d.getHours(),"
                           "d.getMinutes(),d.getTimezoneOffset()].join(',')"));
    printJs(out, engine, QStringLiteral("fall_set_0130"),
            QStringLiteral("var d=new Date(2026,10,1,0,0,0,0);"
                           "d.setHours(1);d.setMinutes(30);d.setSeconds(0);"
                           "d.setMilliseconds(0);"
                           "[d.getFullYear(),d.getMonth()+1,d.getDate(),d.getHours(),"
                           "d.getMinutes(),d.getTimezoneOffset()].join(',')"));
    printJs(out, engine, QStringLiteral("date_roll_forward"),
            QStringLiteral("var d=new Date(2026,11,31,12,0,0,0);d.setDate(d.getDate()+1);"
                           "[d.getFullYear(),d.getMonth()+1,d.getDate(),d.getHours()].join(',')"));

    const QTimeZone halifax("America/Halifax");
    out << "tz_valid=" << halifax.isValid() << '\n';
    for (const auto &[date, time] : {
             std::pair{QDate(2026, 3, 8), QTime(2, 30)},
             std::pair{QDate(2026, 11, 1), QTime(1, 30)},
         }) {
        const QDateTime value(date, time, halifax);
        out << "qt_datetime=" << date.toString(Qt::ISODate) << ','
            << time.toString(QStringLiteral("HH:mm")) << ',' << value.isValid() << ','
            << value.toString(Qt::ISODateWithMs) << ',' << value.offsetFromUtc() << '\n';
    }

    qputenv("TZ", "UTC");
    tzset();
    printJs(out, engine, QStringLiteral("timezone_change_before"),
            QStringLiteral("var pending=new Date(2026,7,11,17,0,0,0);"
                           "[pending.getHours(),pending.getTimezoneOffset(),"
                           "pending.getTime()].join(',')"));
    qputenv("TZ", "America/Halifax");
    tzset();
    printJs(out, engine, QStringLiteral("timezone_change_existing"),
            QStringLiteral("[pending.getHours(),pending.getTimezoneOffset(),"
                           "pending.getTime()].join(',')"));
    printJs(out, engine, QStringLiteral("timezone_change_reconstructed"),
            QStringLiteral("var rebuilt=new Date(2026,7,11,17,0,0,0);"
                           "[rebuilt.getHours(),rebuilt.getTimezoneOffset(),"
                           "rebuilt.getTime()].join(',')"));

    QJsonParseError duplicateError;
    const QJsonDocument duplicate = QJsonDocument::fromJson(
        QByteArrayLiteral("{\"id\":41,\"id\":99}"), &duplicateError);
    const QByteArray serializedDuplicate = duplicate.toJson(QJsonDocument::Compact);
    out << "duplicate_json=" << (duplicateError.error == QJsonParseError::NoError) << ','
        << duplicate.object().value(QStringLiteral("id")).toInt() << ','
        << serializedDuplicate.count("\"id\"") << '\n';
    return 0;
}
