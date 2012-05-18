package static;

use Digest::MD5  qw(md5_hex);
use nginx;

sub handler {
    my $r = shift;
    my $url, $size;

    my $uri = $r->args; 

    while ($uri =~ /((\w+)=([\w\d\%\.]+))/g ) {
        if($2 eq 'url') {
            $url = $3;
        } elsif ($2 eq 's') {
            $size = $3;
        }
    }

    $url =~ s/\%([A-Fa-f0-9]{2})/pack('C', hex($1))/seg;
    my $md5_url = md5_hex($url);
    my $path = '/srv/www/screenshot/static/' . $size . '/' . substr($md5_url, 0, 1) . '/' . substr($md5_url, 1, 1) . '/' . substr($md5_url, 2, 1) . '/' . $md5_url . '.jpg';

    if (-e $path) {
        $r->send_http_header('image/jpeg');
        $r->sendfile($path);
    } else {
        return DECLINED;
    }

    return OK;
}

1;

__END__
