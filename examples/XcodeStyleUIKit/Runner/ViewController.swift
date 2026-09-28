import UIKit

final class ViewController: UIViewController {
    override func viewDidLoad() {
        super.viewDidLoad()

        view.backgroundColor = UIColor(red: 0.06, green: 0.10, blue: 0.18, alpha: 1)

        let circle = UIView(frame: CGRect(x: 92, y: 150, width: 190, height: 190))
        circle.backgroundColor = UIColor(red: 0.08, green: 0.58, blue: 0.92, alpha: 1)
        circle.layer.cornerRadius = 95
        view.addSubview(circle)

        let title = UILabel(frame: CGRect(x: 24, y: 390, width: 327, height: 80))
        title.text = "Built on iPhone"
        title.textColor = .white
        title.font = .boldSystemFont(ofSize: 34)
        title.textAlignment = .center
        view.addSubview(title)

        let subtitle = UILabel(frame: CGRect(x: 24, y: 470, width: 327, height: 70))
        subtitle.text = "UIKit source from an Xcode-style project"
        subtitle.textColor = UIColor(white: 1, alpha: 0.78)
        subtitle.font = .systemFont(ofSize: 18, weight: .medium)
        subtitle.textAlignment = .center
        subtitle.numberOfLines = 0
        view.addSubview(subtitle)
    }
}
